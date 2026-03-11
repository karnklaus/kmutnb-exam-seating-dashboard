# Exam Seating Dashboard

Web dashboard for searching exam seating data from:
- ENG KMUTNB exam seating service
- SCIBASE examroom service

Thai version: [README.th.md](README.th.md)

## Features
- Search by student ID (input can include separators; app sanitizes before search)
- Merge exam seating records from multiple sources
- Unified display for source, student name, course, date/time, room, and seat
- Seat map popup for ENG records
- In-memory cache for faster repeat queries

## Tech Stack
- Python 3.10+
- Flask
- requests
- beautifulsoup4

## Project Structure
- `app.py` - Flask app + source fetch/parsing logic
- `templates/index.html` - frontend view and client-side logic
- `static/style.css` - theme and layout
- `requirements.txt` - dependencies

## Local Setup
1. Create virtual environment
   - Windows PowerShell:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
2. Install dependencies
   ```powershell
   pip install -r requirements.txt
   ```
3. Run app
   ```powershell
   python app.py
   ```
4. Open browser
   - `http://127.0.0.1:5000`

## Notes
- This project scrapes source websites, so HTML changes on source pages may require parser updates.
- Verify usage policy/terms of source websites before production deployment.

## License
MIT (see `LICENSE`).
