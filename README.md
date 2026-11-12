# SoundFont Edit Studio

แอปเดสก์ท็อป Windows สำหรับจัดคลัง SoundFont ทดลองเสียง และจัดชุด preset
หน้าตาโทนสว่างขาว–เขียวอมฟ้า พร้อมสลับปุ่มคำสั่งหลักไทย/อังกฤษ

**สถานะ: รุ่นทดลอง 0.1.0** สร้างใหม่จากขอบเขตที่ตกลงกัน ไม่ได้นำโค้ดจากโปรแกรมเดิมมาใช้

![หน้าจอแอป](docs/preview.png)

## ดาวน์โหลดสำหรับ Windows

เปิด [Windows build](../../actions/workflows/windows.yml) เลือกรอบที่สำเร็จล่าสุด
แล้วดาวน์โหลด `SoundFont-Edit-Studio-Windows` ในส่วน Artifacts
แตก ZIP ทั้งหมด แล้วเปิด `SoundFont-Edit-Studio.exe` โดยเก็บโฟลเดอร์ `_internal` ไว้ด้วยกัน
ใช้ Windows 10/11 แบบ 64 บิต ไม่ต้องติดตั้ง Python แยก

ตัว build รวม FluidSynth สำหรับเล่นเสียงไว้แล้ว ไฟล์ยังไม่ได้ลงลายเซ็นดิจิทัล
และยังต้องทดลองอุปกรณ์เสียง/MIDI จริงบนเครื่องของผู้ใช้

## ความสามารถในรุ่นนี้

- เพิ่มไฟล์ `.sf2` / `.sf3` หรือสแกนโฟลเดอร์ย่อย พร้อมเก็บรายการคลังไว้ข้ามการเปิดโปรแกรม
- เก็บดัชนี preset ใน SQLite โดยตรวจขนาดและเวลาแก้ไขไฟล์ก่อนใช้แคช
- ค้นหาชื่อ preset, ไฟล์, แท็ก, `bank:0`, `program:0`; กรองโฟลเดอร์และรายการโปรด
- ใส่แท็กหลายหมวดโดยคั่นด้วยจุลภาค เช่น `Piano, Acoustic`
- ทดลอง preset ด้วยปุ่มฟังเสียง เปียโนบนจอ คีย์คอมพิวเตอร์ `A W S E D F T G Y H U J K O L P` หรือ MIDI input
- ปรับ Volume และ Velocity; ปุ่มหยุดเสียงสำหรับปิดโน้ตที่ค้าง
- เปลี่ยนชื่อและ Bank/Program ของสำเนา preset ในชุดเสียง ไม่แก้ต้นฉบับ
- คัดลอก preset จากหลาย SF2 เข้าชุด เพิ่มสำเนาซ้ำ ย้ายลำดับ และลบออกจากชุด
- ตรวจ Bank/Program ซ้ำ และปฏิเสธการส่งออกเมื่อซ้ำ
- บันทึก/เปิดโปรเจกต์ `.sfedit` สำหรับกลับมาแก้ต่อ
- รวมและส่งออกชุดเป็น `.sf2` ใหม่ในเบื้องหลัง พร้อมป้องกันเขียนทับไฟล์ต้นทาง

## วิธีใช้

1. เพิ่มโฟลเดอร์หรือไฟล์ SoundFont แล้วเลือก preset ในตารางบน
2. กด **ฟังเสียง** หรือเล่นคีย์บอร์ดทดลองเสียง สำหรับ MIDI ให้กด **ค้นหา MIDI** แล้วเลือกอุปกรณ์
3. แก้ Name/Bank/Program ทางขวา แล้วกด **เพิ่มเข้าชุด**
4. หากต้องการแก้รายการที่เพิ่มแล้ว ให้เลือกในตารางล่าง แก้ค่า แล้วกด **แก้ไขรายการในชุด**
5. **บันทึกโปรเจกต์** เพื่อกลับมาจัดต่อ หรือ **ส่งออก SF2** เพื่อนำชุดไปใช้กับโปรแกรมอื่น

โปรเจกต์อ้างอิงไฟล์เสียงต้นทาง ไม่ได้ฝัง sample ทั้งหมด จึงควรเก็บไฟล์ต้นทางไว้
เส้นทางจะบันทึกแบบสัมพันธ์กับโปรเจกต์เมื่อทำได้ และรองรับไฟล์ที่อยู่ต่างไดรฟ์บน Windows
การเปลี่ยน Bank/Program ในชุดไม่เปลี่ยนหมายเลขที่ใช้ฟังเสียงต้นทาง

## ข้อจำกัดที่ทราบ

- `.sf3` อ่านรายการและทดลองเสียงผ่าน FluidSynth ได้ แต่ยังนำไปรวมส่งออก SF2 ไม่ได้
  เพราะต้องถอดรหัส sample ก่อน โปรแกรมจะแจ้งและไม่สร้างผลลัพธ์ผิดรูปแบบ
- การส่งออกเก็บ **instrument และ sample ทั้งหมดจากแต่ละไฟล์ต้นทางที่ใช้งาน**
  เพื่อคง global zones, modulators, stereo links และ sample ที่ใช้ร่วมกัน
  ยังไม่ตัด sample ที่ไม่ได้ใช้หรือรวม sample ซ้ำ จึงอาจได้ไฟล์ใหญ่กว่าที่คาด
- ยังไม่ส่งออก SoundFont ที่ใช้ข้อมูลเสริม `sm24` (24 บิต) หรือ ROM samples
- ชื่อ preset ใน SF2 ใช้ ASCII สูงสุด 19 ไบต์; อักษรนอก ASCII จะเป็น `?`
  ชื่อเต็มภาษาไทยเก็บในโปรเจกต์ได้
- การเปิดเครื่องเสียงครั้งแรกอาจใช้เวลาโหลดไฟล์เข้าตัวสังเคราะห์เสียง
- ปุ่มคำสั่งหลักและหัวตารางสลับภาษาได้ บางข้อความทางเทคนิค/กล่องแจ้งเตือนยังเป็นภาษาอังกฤษ
- ยังไม่มีตัวแก้ sample, loop, envelope, filter, undo/redo หรือการ relink ไฟล์ที่ย้ายตำแหน่ง

## เรียกจากซอร์ส

ต้องใช้ Python 3.11 ขึ้นไป แนะนำ 3.12 แบบ 64 บิต

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m soundfont_edit.app
```

สำหรับเล่นเสียงบน Windows ให้ดาวน์โหลด FluidSynth Windows x64 จาก
[แหล่งทางการ](https://github.com/FluidSynth/fluidsynth/releases/tag/v2.6.2)
แล้วคัดลอก DLL จาก `bin` ลงโฟลเดอร์ `vendor` ข้างซอร์ส หรือกำหนด runtime ผ่าน PATH
บน Linux ต้องมี `libfluidsynth` และระบบเสียง PulseAudio

## ทดสอบและ build

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --windowed --name SoundFont-Edit-Studio --add-binary "vendor/*.dll;vendor" --add-data "THIRD_PARTY.md;." --hidden-import mido.backends.rtmidi --hidden-import fluidsynth soundfont_edit_launcher.py
```

GitHub Actions ทดสอบบน Windows รวม DLL ที่ตรวจ SHA-256 แล้ว สร้าง portable build
และตรวจว่า executable เปิดค้างได้ การทดสอบเสียงใช้การ render แบบ offline
จึงยังไม่แทนการตรวจเสียงออกลำโพงและ MIDI hardware จริง

ดู [ส่วนประกอบภายนอก](THIRD_PARTY.md) และ [โครงสร้างโปรแกรม](docs/architecture.md)
