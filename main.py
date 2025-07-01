import os
import mido
from mido import MidiFile
import math
import datetime
import logging
from flask import Flask, render_template, request, send_file, redirect, url_for, flash, session
from werkzeug.utils import secure_filename


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'mid', 'midi'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def note_to_freq(note):
    """Convert MIDI note to frequency (Hz)"""
    return int(440 * math.pow(2, (note - 69) / 12))

def ticks_to_ms(ticks, tempo, ticks_per_beat):
    """Convert ticks to milliseconds"""
    return (ticks * tempo) / (ticks_per_beat * 1000)

def process_midi_tracks(midi_file):
    """Process MIDI tracks and extract notes with pauses"""
    ticks_per_beat = midi_file.ticks_per_beat
    tempo = 500000  
    
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

def generate_beep_commands(notes, tempo, ticks_per_beat):
    """Generate beep commands with pauses (beep 0)"""
    events = []
    for note in notes:
        events.append(('start', note['start'], note))
        events.append(('end', note['end'], note))
    

    events.sort(key=lambda x: (x[1], x[0] == 'start'))

    active_notes = []
    commands = []
    last_time = 0
    current_freq = 0

    for event in events:
        time_ms = int(ticks_to_ms(event[1], tempo, ticks_per_beat))
        note = event[2]
        

        if time_ms > last_time:
            duration = time_ms - last_time
            if duration > 0:
                if current_freq > 0:
                    commands.append(f"beep {current_freq} {duration}")
                else:
                    commands.append(f"beep 0 {duration}") 
            last_time = time_ms


        if event[0] == 'start':
            active_notes.append(note)
        else:
            if note in active_notes:
                active_notes.remove(note)
        
        current_freq = max(n['freq'] for n in active_notes) if active_notes else 0

    return commands


@app.route('/', methods=['GET', 'POST'])
def index():
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
            mid = MidiFile(input_path)
            notes, tempo, ticks_per_beat = process_midi_tracks(mid)
            commands = generate_beep_commands(notes, tempo, ticks_per_beat)
            
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
