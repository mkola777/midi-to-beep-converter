import os
import mido
from mido import MidiFile
import math
import datetime
from flask import Flask, render_template, request, send_file, redirect, url_for, flash
from werkzeug.utils import secure_filename
import PySimpleGUI as sg  


app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  
app.config['ALLOWED_EXTENSIONS'] = {'mid', 'midi'}


def note_to_freq(note):
    return int(440 * math.pow(2, (note - 69) / 12))

def ticks_to_ms(ticks, tempo, ticks_per_beat):
    return (ticks * tempo) / (ticks_per_beat * 1000)

def process_midi_tracks(midi_file):
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
    events = []
    for note in notes:
        events.append(('start', note['start'], note))
        events.append(('end', note['end'], note))

    events.sort(key=lambda x: (x[1], x[0] == 'end'))

    active_notes = []
    commands = []
    last_time = 0
    current_freq = 0

    for event in events:
        time_ms = int(ticks_to_ms(event[1], tempo, ticks_per_beat))
        note = event[2]

        if time_ms > last_time:
            duration = time_ms - last_time
            if duration > 0 and current_freq > 0:
                commands.append(f"beep {current_freq} {duration}")
            last_time = time_ms

        if event[0] == 'start':
            active_notes.append(note)
            current_freq = max(n['freq'] for n in active_notes)
        else:
            if note in active_notes:
                active_notes.remove(note)
                current_freq = max(n['freq'] for n in active_notes) if active_notes else 0

    return commands

def convert_midi(input_path, output_path):
    try:
        mid = MidiFile(input_path)
        notes, tempo, ticks_per_beat = process_midi_tracks(mid)
        commands = generate_beep_commands(notes, tempo, ticks_per_beat)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(commands))
        return True, output_path

    except Exception as e:
        return False, f"Conversion error: {str(e)}"

@app.route('/', methods=['GET', 'POST'])
def web_interface():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected!', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No file selected!', 'error')
            return redirect(request.url)

        if not file.filename.lower().endswith(('.mid', '.midi')):
            flash('Only MIDI files (.mid, .midi) are allowed!', 'error')
            return redirect(request.url)

        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(input_path)

        output_filename = f"beep_{os.path.splitext(filename)[0]}.txt"
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)

        success, result = convert_midi(input_path, output_path)

        if success:
            return send_file(output_path, as_attachment=True)
        else:
            flash(result, 'error')
            return redirect(request.url)

    return '''
    <!doctype html>
    <html>
      <head>
        <title>MIDI to BEEP Converter</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 20px; }
          h1 { color: #333; }
          form { margin-top: 20px; }
          .error { color: red; }
        </style>
      </head>
      <body>
        <h1>MIDI to BEEP Converter</h1>
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <div class="error">{{ messages[0] }}</div>
          {% endif %}
        {% endwith %}
        <form method=post enctype=multipart/form-data>
          <input type=file name=file accept=".mid,.midi">
          <input type=submit value=Convert>
        </form>
      </body>
    </html>
    '''

def local_gui():
    sg.theme('DarkBlue3')

    layout = [
        [sg.Text('MIDI to BEEP Converter', font=('Helvetica', 16))],
        [sg.Text('Select MIDI file:'), sg.Input(key='-INPUT-'), 
         sg.FileBrowse(file_types=(("MIDI Files", "*.mid"),))],
        [sg.Text('Save as:'), sg.Input(key='-OUTPUT-'), 
         sg.SaveAs(file_types=(("Text Files", "*.txt"),))],
        [sg.Button('Convert'), sg.Button('Exit')],
        [sg.Multiline(size=(60, 10), key='-LOG-', autoscroll=True)]
    ]

    window = sg.Window('MIDI to BEEP Converter', layout)

    while True:
        event, values = window.read()

        if event in (sg.WIN_CLOSED, 'Exit'):
            break

        if event == 'Convert':
            input_file = values['-INPUT-']
            output_file = values['-OUTPUT-']

            if not input_file:
                sg.popup_error("Error", "No MIDI file selected!")
                continue

            if not output_file:
                sg.popup_error("Error", "No output file specified!")
                continue

            success, result = convert_midi(input_file, output_file)

            if success:
                with open(result, 'r', encoding='utf-8') as f:
                    content = f.read()
                window['-LOG-'].print(f"Success! File saved to:\n{result}")
                window['-LOG-'].print("\nGenerated commands:")
                window['-LOG-'].print(content)
                sg.popup("Success!", f"BEEP commands saved to:\n{result}")
            else:
                window['-LOG-'].print(result)
                sg.popup_error("Error", result)

    window.close()

if __name__ == '__main__':
    import sys
    if '--web' in sys.argv:  
        app.run(host='0.0.0.0', port=8080)
    else:  
        local_gui()