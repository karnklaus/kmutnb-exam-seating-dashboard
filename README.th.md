# Exam Seating Dashboard (ภาษาไทย)

แดชบอร์ดสำหรับค้นหาข้อมูลที่นั่งสอบของนักศึกษา จาก 2 แหล่งข้อมูล:
- ENG KMUTNB
- SCIBASE

[English README](README.md)

## ความสามารถหลัก
- ค้นหาด้วยรหัสนักศึกษา (รองรับการกรอกแบบมีเครื่องหมายคั่น และระบบจะจัดรูปแบบก่อนค้นหา)
- รวมผลลัพธ์จากหลายแหล่งให้อยู่ในรูปแบบเดียวกัน
- แสดงข้อมูลรายวิชา วัน/เวลา ห้องสอบ ที่นั่ง และแหล่งข้อมูล
- มีปุ่มดูผังที่นั่งสำหรับข้อมูลที่รองรับ
- มี cache ในหน่วยความจำเพื่อให้ค้นหาซ้ำได้เร็วขึ้น

## เทคโนโลยีที่ใช้
- Python 3.10+
- Flask
- requests
- beautifulsoup4

## โครงสร้างโปรเจกต์
- `app.py` - Flask app + logic ดึง/แปลงข้อมูล
- `templates/index.html` - หน้าเว็บและ JavaScript ฝั่ง client
- `static/style.css` - ธีมและการจัดวาง UI
- `requirements.txt` - รายการแพ็กเกจที่ต้องใช้

## วิธีรันในเครื่อง
1. สร้าง virtual environment
   - Windows PowerShell:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
2. ติดตั้ง dependencies
   pip install -r requirements.txt
3. รันโปรเจกต์
   python app.py
4. เปิดใช้งาน
   - `http://127.0.0.1:5000`

## หมายเหตุ
- โปรเจกต์นี้ใช้วิธีดึงข้อมูลจากหน้าเว็บต้นทาง (scraping) หากโครงสร้าง HTML เปลี่ยน อาจต้องปรับ parser
- ควรตรวจสอบข้อกำหนดการใช้งานเว็บไซต์ต้นทางก่อนนำไปใช้จริงในระบบ production

## License
MIT (ดูไฟล์ `LICENSE`)
