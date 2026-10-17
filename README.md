# V0 Converter - Lossless Audio to MP3 V0 Converter

A GUI application to convert lossless audio files (FLAC, WAV, AIFF, etc.) to MP3 V0 format while preserving folder structure, metadata, and album art.

## Features

- Convert lossless audio files to high-quality MP3 V0 (variable bit rate)
- Preserve metadata and album art during conversion
- Maintain folder structure in the output
- Copy non-lossless files without conversion
- Batch mode to convert multiple albums at once
- Parallel processing to speed up conversion

## Requirements

- **FFmpeg**: Must be installed and available in your system PATH
  - Windows: [Download from ffmpeg.org](https://ffmpeg.org/download.html)
  - macOS: Install via Homebrew: `brew install ffmpeg`
  - Linux: Install via package manager (e.g., `apt install ffmpeg`)

## Usage

1. **Select Source Base Folder**: This is your root music folder (e.g., "Music/")
2. **Select Source Subfolder**: The specific album or artist folder to convert
3. **Enable Batch Mode** (optional): Convert all subdirectories in the source base folder
4. **Configure Parallel Processing** (optional): Enable/disable and set number of threads
5. **Select Target Base Folder**: Where converted files will be saved
6. **Click "Start Conversion"**: The app will convert all lossless files and copy non-lossless files

## Output Structure

If your source structure is: `Music/Artist/Album/song.flac`  
Then your output will be: `Lossy Music/Artist/Album/song.mp3`

Any directory named "FLAC" will be renamed to "MP3V0" in the output path.

## Notes

- The app preserves directory structure in the target location
- Album art is embedded in the MP3 files if found in the source folder
- The app handles album art optimization, only replacing existing art if the new art is higher resolution
- This application requires an active internet connection and administrator privileges to install dependencies

## Troubleshooting

If you encounter errors:

1. Ensure FFmpeg is installed and in your PATH
2. Check that you have proper permissions to read source files and write to the target location
3. Verify that source files are not corrupted
4. Make sure you have sufficient disk space in the target location