import subprocess

def createVaults(number):
    i = 0
    while i < number:
        subprocess.run(f"op vault create vault{i}", shell=True, check=True, capture_output=True)
        i += 1

createVaults(4)