FROM python:3.11-slim

WORKDIR /app

# UPDATE: Hapus library grafis, TAPI pertahankan GCC
# GCC wajib ada untuk menginstall 'psutil' dan 'eventlet' di Linux
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip

# Install library (Sekarang jauh lebih cepat tanpa OpenCV)
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p myDrive_data

EXPOSE 5000

# Jalankan aplikasi
CMD ["gunicorn", "-k", "eventlet", "-w", "1", "-b", "0.0.0.0:5000", "app:app"]