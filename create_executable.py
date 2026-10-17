import os
import sys
import subprocess
import shutil
import platform

def check_dependencies():
    """Check for required dependencies before building."""
    missing_deps = []
    
    # Check for PyInstaller
    try:
        import PyInstaller
        print("PyInstaller is installed.")
    except ImportError:
        missing_deps.append("pip install pyinstaller")
    
    # Check for Pillow
    try:
        import PIL
        print("Pillow is installed.")
    except ImportError:
        missing_deps.append("pip install pillow")
        
    # Check for mutagen
    try:
        import mutagen
        print("Mutagen is installed.")
    except ImportError:
        missing_deps.append("pip install mutagen")
    
    # Check for ffmpeg (only a runtime dependency, not needed for building)
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("ffmpeg is installed and in PATH.")
    except FileNotFoundError:
        print("Warning: ffmpeg not found in PATH. The executable will still build, but users will need ffmpeg installed.")
        
    return missing_deps

def create_executable():
    print("Starting build process for V0 Converter executable...")
    
    # Determine system-specific settings
    is_windows = platform.system() == "Windows"
    icon_param = "--icon=app_icon.ico" if is_windows and os.path.exists("app_icon.ico") else ""
    
    # Set PyInstaller command using Python module execution
    pyinstaller_args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",  # Create a single executable file
        "--windowed",  # Don't show the console window when running the app
        "--name", "V0Converter",
        icon_param,
        "--add-data", f"README.md{';' if is_windows else ':'}.",  # Include README if it exists
        "v0conv.py"
    ]
    
    # Filter out empty arguments
    pyinstaller_args = [arg for arg in pyinstaller_args if arg]
    
    # Run PyInstaller
    print("Running PyInstaller with command:", " ".join(pyinstaller_args))
    result = subprocess.run(pyinstaller_args, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("Build completed successfully!")
        
        # Show output location
        dist_path = os.path.abspath("dist")
        executable_name = "V0Converter.exe" if is_windows else "V0Converter"
        print(f"Executable created at: {os.path.join(dist_path, executable_name)}")
        
        # Add a note about ffmpeg
        print("\nIMPORTANT: The executable requires ffmpeg to be installed and in the PATH.")
        print("When distributing this application, make sure to inform users about this requirement.")
    else:
        print("Build failed with the following errors:")
        print(result.stderr)

if __name__ == "__main__":
    print("V0 Converter Executable Builder")
    print("==============================")
    
    # Check dependencies
    missing = check_dependencies()
    if missing:
        print("\nMissing dependencies detected. Please install the following:")
        for dep in missing:
            print(f"  {dep}")
        print("\nAfter installing the required packages, run this script again.")
        sys.exit(1)
    
    # Prompt user to continue
    print("\nReady to build the executable. This may take a few minutes.")
    input("Press Enter to continue...")
    
    # Create the executable
    create_executable()
    
    print("\nBuild process completed.")
    if platform.system() == "Windows":
        input("Press Enter to exit...")