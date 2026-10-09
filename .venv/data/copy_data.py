import os
import shutil

# Source and destination directory paths
source_dir = r"D:\Downloads"
destination_dir = r"C:\AI Agent Project\.venv\data"

# Create the target directory if it doesn't exist
os.makedirs(destination_dir, exist_ok=True)

files = ["payments.csv", "users.csv", "vehicles.csv", "rides.csv", "ratings.csv"]

for file in files:
    source_path = os.path.join(source_dir, file)
    destination_path = os.path.join(destination_dir, file)

    if os.path.exists(source_path):
        shutil.copy(source_path, destination_path)
        print(f"Successfully saved '{file}' to {destination_path}")
    else:
        print(f"Warning: '{file}' was not found in {source_dir}")