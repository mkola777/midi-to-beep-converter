import os
import mido
from mido import MidiFile
import math
import logging
from flask import Flask, render_template, request, send_file, redirect, url_for, flash, session
from werkzeug.utils import secure_filename

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')  # Безопаснее использовать переменные окружения
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'mid', 'midi'}

# Создание папки для загрузок
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    """Проверка разрешенных расширений файлов"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def note_to_freq(note):
    """Конвертация MIDI ноты в частоту (Гц)"""
    return int(440 * math.pow(2, (note - 69) / 12))

def ticks_to_ms(ticks, tempo, ticks_per_beat):
    """Конвертация тиков в миллисекунды"""
    return (ticks * tempo) / (ticks_per_beat * 1000)

def process_midi_tracks(midi_file):
    """Обработка MIDI треков и извлечение нот"""
    ticks_per_beat = midi_file.ticks_per_beat
    tempo = 500000  # Стандартный темп (120 BPM)
    
    # Поиск установки темпа в треках
    for track in midi_file.tracks:
        for msg in track:
            if msg.type == 'set_tempo':
                tempo = msg.tempo
                break

    notes = []
    for track in midi_file.tracks:
        current_time = 0
        active_notes = {}
        
        for msg in track:
            current_time += msg.time
            
            if msg.type == 'note_on' and msg.velocity > 0:
                active_notes[msg.note] = current_time
            elif (msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0)):
                if msg.note in active_notes:
                    start_time = active_notes.pop(msg.note)
                    notes.append({
                        'note': msg.note,
                        'start': start_time,
                        'end': current_time,
                        'freq': note_to_freq(msg.note)
                    })

    return notes, tempo, ticks_per_beat

# Система перевода
translations = {
    'en': {
        'title': 'MIDI to BEEP Converter',
        'description': 'Upload a MIDI file (.mid or .midi) to convert it to BEEP commands.',
        'select_file': 'Select MIDI file',
        'convert': 'Convert',
        'no_file': 'No file selected!',
        'invalid_file': 'Only MIDI files (.mid, .midi) are allowed!',
        'success': 'Success!',
        'success_msg': 'MIDI file has been converted to BEEP commands.',
        'commands': 'BEEP commands',
        'output_file': 'Output file',
        'preview': 'Commands preview:',
        'download': 'Download file',
        'convert_another': 'Convert another file',
        'conversion_complete': 'Conversion complete!',
        'error': 'Error',
        'file_not_found': 'File not found!',
        'and': 'and',
        'more_commands': 'more commands'
    },
    'ru': {
        'title': 'MIDI в BEEP Конвертер',
        'description': 'Загрузите MIDI файл (.mid или .midi) для конвертации в BEEP команды.',
        'select_file': 'Выберите MIDI файл',
        'convert': 'Конвертировать',
        'no_file': 'Файл не выбран!',
        'invalid_file': 'Разрешены только MIDI файлы (.mid, .midi)!',
        'success': 'Успешно!',
        'success_msg': 'MIDI файл был конвертирован в BEEP команды.',
        'commands': 'BEEP команд',
        'output_file': 'Выходной файл',
        'preview': 'Предварительный просмотр команд:',
        'download': 'Скачать файл',
        'convert_another': 'Конвертировать еще один файл',
        'conversion_complete': 'Конвертация завершена!',
        'error': 'Ошибка',
        'file_not_found': 'Файл не найден!',
        'and': 'и',
        'more_commands': 'дополнительных команд'
    }
}

def get_lang():
    """Получение текущего языка из сессии"""
    return session.get('language', 'en')

def get_text(key):
    """Получение переведенного текста"""
    lang = get_lang()
    return translations[lang].get(key, translations['en'][key])

@app.route('/set_language/<language>')
def set_language(language):
    """Установка языка интерфейса"""
    if language in translations:
        session['language'] = language
    return redirect(request.referrer or url_for('index'))

def generate_beep_commands(notes, tempo, ticks_per_beat):
    """Генерация beep-команд для CMD"""
    events = []
    for note in notes:
        events.append(('start', note['start'], note))
        events.append(('end', note['end'], note))
    
    # Сортировка событий по времени
    events.sort(key=lambda x: (x[1], x[0] == 'end'))

    active_notes = []
    commands = []
    last_time = 0
    current_freq = 0

    for event in events:
        time_ms = int(ticks_to_ms(event[1], tempo, ticks_per_beat))
        note = event[2]
        
        # Обработка промежутков между событиями
        if time_ms > last_time:
            duration = time_ms - last_time
            if duration > 0 and current_freq > 0:
                commands.append(f"beep {current_freq} {duration}")
            last_time = time_ms

        # Обновление активных нот
        if event[0] == 'start':
            active_notes.append(note)
            current_freq = max(n['freq'] for n in active_notes)
        else:
            if note in active_notes:
                active_notes.remove(note)
                current_freq = max(n['freq'] for n in active_notes) if active_notes else 0

    return commands

@app.route('/', methods=['GET', 'POST'])
def index():
    """Главная страница с формой загрузки"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash(get_text('no_file'), 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash(get_text('no_file'), 'error')
            return redirect(request.url)

        if not allowed_file(file.filename):
            flash(get_text('invalid_file'), 'error')
            return redirect(request.url)

        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(input_path)

        output_filename = f"beep_{os.path.splitext(filename)[0]}.txt"
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)

        try:
            logger.info(f"Processing MIDI file: {filename}")
            mid = MidiFile(input_path)
            notes, tempo, ticks_per_beat = process_midi_tracks(mid)
            commands = generate_beep_commands(notes, tempo, ticks_per_beat)
            
            logger.info(f"Generated {len(commands)} BEEP commands")

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(commands))

            return render_template('result.html',
                                filename=output_filename,
                                commands=commands,
                                download_link=output_filename,
                                get_text=get_text,
                                current_lang=get_lang())
        except Exception as e:
            logger.error(f"Error processing MIDI file: {str(e)}", exc_info=True)
            flash(f'{get_text("error")}: {str(e)}', 'error')
            if os.path.exists(input_path):
                os.remove(input_path)
            return redirect(request.url)

    return render_template('index.html', get_text=get_text, current_lang=get_lang())

@app.route('/download/<filename>')
def download(filename):
    """Скачивание результата"""
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(path):
        flash(get_text('file_not_found'), 'error')
        return redirect(url_for('index'))
    return send_file(path, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
