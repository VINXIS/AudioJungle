import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pydub import AudioSegment
import threading
import traceback
import math
import re
import subprocess
import sys
import os

# Lowest gain DB
min_amplitude = 0.000001

# Keep track of running FFmpeg subprocesses
ffmpeg_processes = [] 

def custom_crossfade(audio1, audio2, crossfade_duration_ms):

    # Calculate fade step
    fade_step = 1 / crossfade_duration_ms

    # Initialize the crossfaded audio
    crossfaded = AudioSegment.empty()

    for i in range(crossfade_duration_ms):
        # Calculate the current volume level using the ease-in-out sine function
        volume_factor = i * fade_step
        gain1 = 20 * math.log10((1 - min_amplitude) * (1 - volume_factor) + min_amplitude)
        gain2 = 20 * math.log10((1 - min_amplitude) * volume_factor + min_amplitude)

        # Apply volume adjustment
        segment1 = audio1[-crossfade_duration_ms + i:-crossfade_duration_ms + i + 1].apply_gain(gain1)
        segment2 = audio2[i:i + 1].apply_gain(gain2)

        # Overlay the segments
        crossfaded += segment1.overlay(segment2)

    return crossfaded

def create_ffmpeg_command(loop_amount, output_file):
    # Construct the command to concatenate intro, loop (repeated), and outro
    with open("concat_list.txt", "w") as f:
        f.write(f"file 'intro.wav'\n")
        for _ in range(loop_amount):
            f.write(f"file 'loop.wav'\n")
        f.write(f"file 'outro.wav'\n")

    if output_file.endswith('.mp3'):
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", "concat_list.txt",
            "-q:a", "2",  # Adjust MP3 quality with -q:a, where a lower number is higher quality. 2 is generally high quality.
            output_file
        ]
    else: # Assume output file is .wav (currently not possible to select other formats)
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", "concat_list.txt",
            "-c", "copy",
            output_file
        ]

    return cmd

def update_progress(current, total):
    percentage = min(1, current / total) * 100
    progress['value'] = percentage
    if current == 0 and total == 1:
        progress_label.config(text="")
    else:
        progress_label.config(text=f"{percentage:.0f}% completed")
    root.update_idletasks()

def cleanup_temp_files():
    temp_files = ["intro.wav", "loop.wav", "outro.wav", "concat_list.txt"]
    for file in temp_files:
        try:
            os.remove(file)
            print(f"Deleted temporary file: {file}")
        except OSError as e:
            print(f"Error deleting temporary file {file}: {e}")

def execute_ffmpeg_command(cmd, total_duration_ms):
    root.after(0, lambda: ffmpeg_output.delete(1.0, tk.END))
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)
    ffmpeg_processes.append(process)  # Keep track of the process

    def update_ffmpeg_output():
        # Regex to match the time progress
        regex = re.compile(r"time=(\d+:\d+:\d+\.\d+)")

        while True:
            line = process.stderr.readline()
            if not line:
                break
            
            root.after(0, lambda l=line: ffmpeg_output.insert(tk.END, l)) # Update the output text area
            root.after(0, lambda: ffmpeg_output.see(tk.END))  # Scroll to the bottom of the text area

            # Parse the time progress
            match = regex.search(line)
            if match:
                current_time = match.group(1)
                # Convert HH:MM:SS.ms to milliseconds
                h, m, s = map(float, current_time.split(":"))
                current_time_ms = (h * 3600 + m * 60 + s) * 1000
                progress = current_time_ms / total_duration_ms
                update_progress(progress, 1)  # Update your progress bar here

    threading.Thread(target=update_ffmpeg_output, daemon=True).start()
    process.wait()  # Wait for the process to complete
    if process.returncode != 0:
        messagebox.showerror("FFmpeg Error", f"An error occurred while creating the loop: {process.stderr.read()}")
        return
    
    cleanup_temp_files()
    messagebox.showinfo("Success", "Audio loop created successfully!")
    update_progress(0, 1)

    ffmpeg_processes.remove(process)  # Remove the process from the list

def create_loop(audio_file, start_time, end_time, crossfade_duration, output_file, time_unit, total_duration_hours, is_test=False):
    try:
        audio = AudioSegment.from_file(audio_file)
        start_time_ms = start_time * (1000 if time_unit == 's' else 1)
        end_time_ms = end_time * (1000 if time_unit == 's' else 1)
        crossfade_duration_ms = crossfade_duration * (1000 if time_unit == 's' else 1)
        if start_time_ms > end_time_ms:
            raise ValueError("Start time cannot be greater than end time")
        if end_time_ms > len(audio):
            raise ValueError("End time cannot be greater than the audio length")
        if start_time_ms < 0:
            raise ValueError("Start time cannot be negative")
        if crossfade_duration < 0:
            raise ValueError("Crossfade duration cannot be negative")
        if total_duration_hours < 0:
            raise ValueError("Total duration cannot be negative")
        if crossfade_duration_ms > start_time_ms:
            raise ValueError("Crossfade duration cannot be greater than start time")
        if crossfade_duration_ms > end_time_ms - start_time_ms:
            raise ValueError("Crossfade duration cannot be greater than the loop duration")

        initial_audio = audio[:end_time_ms]
        loop_segment = audio[start_time_ms - crossfade_duration_ms:end_time_ms]
        crossfade = custom_crossfade(initial_audio, loop_segment, crossfade_duration_ms)

        initial_audio[:-crossfade_duration_ms].export("intro.wav", format="wav")
        (crossfade + loop_segment[crossfade_duration_ms:len(loop_segment)-crossfade_duration_ms]).export("loop.wav", format="wav")
        (crossfade + audio[start_time_ms:]).export("outro.wav", format="wav")

        # Total duration in milliseconds
        if is_test:
            total_duration_ms = len(initial_audio[:-crossfade_duration_ms]) + len(crossfade) + len(audio[start_time_ms:])
            loop_amount = 1
        else:
            total_duration_ms = total_duration_hours * 60 * 60 * 1000
            loop_amount = (total_duration_ms - len(initial_audio[:-crossfade_duration_ms]) - len(crossfade) - len(audio[start_time_ms:])) // (end_time_ms - start_time_ms)
        
        cmd = create_ffmpeg_command(loop_amount, output_file)
        threading.Thread(target=execute_ffmpeg_command, args=(cmd,total_duration_ms), daemon=True).start()
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred: {str(e)}")
        print(''.join(traceback.format_tb(e.__traceback__)))

def save_file():
    file_path = filedialog.asksaveasfilename(defaultextension=".mp3", filetypes=[("MP3 files", "*.mp3")])
    return file_path

def start_loop_creation(is_test=False):
    audio_file = file_path.get()
    start_time = int(start_time_var.get())
    end_time = int(end_time_var.get())
    crossfade_duration = int(crossfade_duration_var.get())
    time_unit = time_unit_var.get()
    total_duration_hours = int(total_duration_var.get())
    output_file = save_file()
    if output_file:
        threading.Thread(target=create_loop, args=(audio_file, start_time, end_time, crossfade_duration, output_file, time_unit, total_duration_hours, is_test), daemon=True).start()

def select_file():
    selected_file = filedialog.askopenfilename()
    if selected_file:  # Check if a file was selected
        file_path.delete(0, tk.END)
        file_path.insert(0, selected_file)

def on_closing():
    if len(ffmpeg_processes) == 0:
        root.destroy()
        return

    for process in ffmpeg_processes:
        process.terminate()  # Attempt to terminate the process
        process.wait()  # Wait for the process to terminate
    cleanup_temp_files()  # Clean up temporary files after FFmpeg processes are terminated
    root.destroy()

root = tk.Tk()
root.title("Echo Blend")
root.iconbitmap(sys.executable)
root.protocol("WM_DELETE_WINDOW", on_closing)  # Bind the close event

file_path = tk.Entry(root, width=50)
file_path.grid(row=0, column=1, padx=10, pady=10)
file_path.insert(0, "Select your audio file...")

browse_button = tk.Button(root, text="Browse", command=select_file)
browse_button.grid(row=0, column=2, padx=10, pady=10)

start_time_var = tk.StringVar()
tk.Label(root, text="Start Time:").grid(row=1, column=0)
tk.Entry(root, textvariable=start_time_var).grid(row=1, column=1)

end_time_var = tk.StringVar()
tk.Label(root, text="End Time:").grid(row=2, column=0)
tk.Entry(root, textvariable=end_time_var).grid(row=2, column=1)

crossfade_duration_var = tk.StringVar()
tk.Label(root, text="Crossfade Duration:").grid(row=3, column=0)
tk.Entry(root, textvariable=crossfade_duration_var).grid(row=3, column=1)

time_unit_var = tk.StringVar(value="ms")
tk.Label(root, text="Time Unit:").grid(row=4, column=0)
tk.OptionMenu(root, time_unit_var, "s", "ms").grid(row=4, column=1, padx=10, pady=10)

total_duration_var = tk.StringVar()
tk.Label(root, text="Total Duration (hours):").grid(row=5, column=0)
tk.Entry(root, textvariable=total_duration_var).grid(row=5, column=1)
total_duration_var.set("10")

progress = ttk.Progressbar(root, orient=tk.HORIZONTAL, length=250, mode='determinate')
progress.grid(row=6, column=1, pady=20)

progress_label = tk.Label(root)
progress_label.grid(row=6, column=2, pady=10)

create_button = tk.Button(root, text="Create Loop", command=lambda: start_loop_creation(is_test=False))
create_button.grid(row=7, column=0, padx=10, pady=10)

test_button = tk.Button(root, text="Test Loop", command=lambda: start_loop_creation(is_test=True))
test_button.grid(row=7, column=1, padx=10, pady=10)

ffmpeg_output = tk.Text(root, height=10, width=50)
ffmpeg_output.grid(row=8, column=0, columnspan=3, padx=10, pady=10)

root.mainloop()
