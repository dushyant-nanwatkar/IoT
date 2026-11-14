from pathlib import Path
from io import BytesIO
import fitz
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph,Table,TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from PIL import Image
R=Path(__file__).resolve().parents[2]; W=Path(__file__).parent
O=R/'output/pdf/AI_and_CV_Home_Security_Reformatted.pdf';O.parent.mkdir(parents=True,exist_ok=True)
for n,f in [('T','times.ttf'),('TB','timesbd.ttf')]:pdfmetrics.registerFont(TTFont(n,'C:/Windows/Fonts/'+f))
B=BytesIO();c=canvas.Canvas(B,pagesize=(595.25,842));page=2
style=ParagraphStyle('body',fontName='T',fontSize=14,leading=20.15,spaceAfter=5)
def para(t,y,x=56.8,w=481.6,size=14,bold=False):
 s=ParagraphStyle('p',parent=style,fontSize=size,leading=size*1.44,fontName='TB' if bold else 'T');p=Paragraph(t,s);_,h=p.wrap(w,750);assert y+h<778,(page,t[:40],y,h);p.drawOn(c,x,842-y-h);return y+h+5
def title(t):return para(t,57,size=16,bold=True)+5
def end():
 global page
 c.setFillColor(colors.black);c.setFont('T',14);c.drawRightString(538,32,str(page));c.showPage();page+=1
def cap(t,y):
 p=Paragraph(t,ParagraphStyle('cap',parent=style,fontName='TB',fontSize=12,leading=17,alignment=1));_,h=p.wrap(481,80);p.drawOn(c,57,842-y-h);return y+h+10
def box(t,x,y,w=140,h=48,fill='#e2f0d9'):
 c.setFillColor(colors.HexColor(fill));c.setStrokeColor(colors.HexColor('#707070'));c.setLineWidth(.65);c.roundRect(x,842-y-h,w,h,3,fill=1,stroke=1)
 p=Paragraph(t,ParagraphStyle('b',fontName='T',fontSize=10.5,leading=13,alignment=1));_,ph=p.wrap(w-10,h);p.drawOn(c,x+5,842-y-(h+ph)/2)
def arrow(x,y,xx,yy):
 import math
 c.setStrokeColor(colors.HexColor('#777777'));c.setLineWidth(.7);c.line(x,842-y,xx,842-yy);a=math.atan2(yy-y,xx-x)
 for d in [-.45,.45]:c.line(xx,842-yy,xx-6*math.cos(a+d),842-(yy-6*math.sin(a+d)))
def grid(labels,edges,y=110,cols=3,h=55,step=95):
 w=(481-20*(cols-1))/cols;pos=[]
 for i,t in enumerate(labels):
  x=57+(i%cols)*(w+20);yy=y+(i//cols)*step;pos.append((x,yy));box(t,x,yy,w,h,['#dce9fa','#e1f4e5','#fff8cc'][i%3])
 for a,b in edges:
  x,yy=pos[a];xx,yyy=pos[b]
  if yyy==yy:arrow(x+w,yy+h/2,xx,yyy+h/2)
  else:
   mid=yy+h+18;c.setStrokeColor(colors.HexColor('#777777'));c.line(x+w/2,842-yy-h,x+w/2,842-mid);c.line(x+w/2,842-mid,xx+w/2,842-mid);arrow(xx+w/2,mid,xx+w/2,yyy)
 return y+((len(labels)-1)//cols)*step+h+20
def table(rows,y,widths=(145,336)):
 st=ParagraphStyle('cell',fontName='T',fontSize=11,leading=14)
 data=[[Paragraph(str(v),st) for v in row] for row in rows];t=Table(data,colWidths=widths)
 t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.HexColor('#b8c9ab')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7e6e6')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]));_,h=t.wrap(481,700);assert y+h<778;t.drawOn(c,57,842-y-h);return y+h+10
topics=['Purpose and Requirements','Process Specification','Domain Model Specification','Information Model Specification','Service Specification','IoT Level Specification','Functional View Specification','Operational View Specification','Device and Component Integration','Application Development']
y=title('Index')
for i,(t,p) in enumerate(zip(topics,[3,4,5,6,7,8,9,10,11,13]),1):
 text=f'{i}. {t}';c.setFont('T',14);c.drawString(57,842-y-14,text);c.drawRightString(538,842-y-14,str(p));tw=c.stringWidth(text,'T',14);c.setDash(1,2);c.line(62+tw,842-y-15,518,842-y-15);c.setDash();y+=23
end()
y=title('1. Purpose and Requirements')
for a,b in [
('Purpose','A local home-security and visitor communication system that observes the doorway, detects persons, compares enrolled faces and presents events on a homeowner dashboard.'),
('Behaviour','An Android endpoint supplies camera and microphone input over Wi-Fi or USB ADB. The local host uses YOLO11, InsightFace and OpenCV, applies a configured three-second unknown dwell rule, stores events and snapshots, and routes notices and return audio.'),
('System management requirement','Provide resident enrollment, event history, notices, intercom, camera commands and device status. IR presence sensing, proximity measurement and controlled lighting are proposed extensions.'),
('Data analysis requirement','Perform person detection, face-embedding comparison and approximate dwell tracking on the local computer. Thresholds and configured processing rates require installation testing.'),
('Application deployment requirement','Host FastAPI, SQLite, media files and the browser dashboard locally. Android capture and feedback follow the assumed client contract; Android source is not supplied.'),
('Security requirement','Restrict administrative and biometric access, protect stored media and add authenticated access. Strict offline operation requires disabled cloud sync, preloaded models and an offline alternative to Edge TTS.')]:
 y=para('•',y,75,15);y-=25.15;y=para('<b>'+a+':</b> '+b,y,93,445)
end()
title('2. Process Specification')
y=grid(['Doorway endpoint<br/>Capture camera and audio','Local host<br/>Receive and decode stream','AI worker<br/>Detect persons and faces','Compare enrolled faces<br/>Known or unknown result','Known: display greeting<br/>with per-name cooldown','Unknown: measure dwell<br/>and apply warning rule','Unknown dwell exceeds 3 s<br/>Save warning and snapshot','Homeowner dashboard<br/>Review stream and event','Visitor response<br/>Notice or two-way audio'],[(0,1),(1,2),(2,3),(3,4),(5,6),(6,7),(7,8)],y=112,step=120)
y=cap('Process specification for AI and CV Powered Home Security System',y)
para('The stream and analysis loops continue while connected. Unknown status is a review cue and does not establish intrusion. Sensor-triggered capture and lighting remain proposed.',y,size=12);end()
y=title('3. Domain Model Specification')
for t in ['<b>Physical Entity:</b> Home entrance and people approaching the doorway.','<b>Virtual Entity:</b> Doorway state, visitor track, enrolled resident and security event.','<b>Devices:</b> Android camera/audio endpoint and local AI computer; proposed IR sensor, proximity sensor, USB controller and lamp.','<b>Service:</b> Media transport, local vision, event storage, notices and intercom.']:y=para(t,y)
y=grid(['User<br/>Homeowner','Virtual entity<br/>Doorway and visitor state','Physical entity<br/>Entrance and visitors','Application<br/>Browser dashboard','Resource<br/>Frames audio embeddings','Device<br/>Phone and local host','Service<br/>Vision alerts intercom','Storage<br/>SQLite and media files','Proposed peripherals<br/>Sensors controller lamp'],[(0,3),(1,4),(2,5),(3,6),(4,7),(5,8)],y=y+15,step=100)
cap('Domain Model specification for AI and CV Powered Home Security System',y);end()
title('4. Information Model Specification')
y=grid(['Doorway state<br/>Digital representation','Resident identity<br/>name role embedding photo','Security event<br/>type severity message snapshot','Voice note<br/>audio transcript duration sender','Device telemetry<br/>battery charging temperature ADB','Kiosk notice<br/>text active created_at'],[],y=110,cols=2,step=110,h=65)
y=cap('Information Model specification for the home security system',y)
y=table([['Entity','Principal stored attributes'],['enrolled_faces','id; name; role; custom_greeting; embedding_json; photo_path'],['security_events','id; event_type; severity; message; snapshot_path; metadata_json'],['voice_notes','id; audio_path; transcript; duration_sec; sender_name'],['device_telemetry','id; battery_pct; is_charging; temp_c; adb_connected'],['kiosk_notices','id; text; active; created_at']],y)
para('All records include timestamps. These five implemented tables have no declared foreign keys. Diagram links express conceptual grouping, not enforced database relationships. Media paths refer to files backed up alongside SQLite.',y,size=12);end()
y=title('5. Service Specification');y=para('Services provided by the system are:',y)
for t in ['1. Receive live video and audio from the doorway endpoint.','2. Detect persons, compare enrolled faces and evaluate unknown dwell.','3. Store events and snapshots and display them on the dashboard.','4. Send notices, greetings and bidirectional intercom audio.']:y=para(t,y,75,463)
y=cap('Communication service',y)
y=table([['Field','Specification'],['Name','Media communication'],['Type','SBMP over TCP; HTTP REST and WebSocket'],['Input','H.264 video, PCM audio, commands and telemetry'],['Output','Decoded frames, dashboard updates and phone feedback'],['Schedule','Continuous; 30 Hz broadcast target, not measured throughput']],y)
y=cap('Person and face analysis service',y)
y=table([['Field','Specification'],['Name','Local person detection and face comparison'],['Host','Python worker on the local computer'],['Input','Latest camera frame and enrolled face embeddings'],['Output','Person boxes, identity matches, dwell events and snapshots'],['Configuration','12 Hz AI target; YOLO confidence 0.45; face threshold 0.48']],y)
para('Proposed sensor and lamp services require controller firmware and host integration. Model thresholds and timing must be calibrated on the installed system.',y,size=12);end()
y=title('6. IoT Level Specification')
y=para('The intended deployment is Level 1 style: one local processing authority performs analysis, stores data and hosts the application. The Android endpoint provides camera, microphone, display and speaker functions. The physical phone and computer are separate devices, so Level 1 is a qualified composite-node interpretation rather than a literal single-device installation.',y)
y=grid(['LOCAL: doorway endpoints<br/>Phone camera mic screen speaker','LOCAL: computer<br/>FastAPI and AI worker','LOCAL: resources<br/>Decoded frames and face embeddings','LOCAL: persistence<br/>SQLite snapshots and audio','LOCAL: application<br/>Homeowner browser dashboard','CLOUD<br/>Not required in intended local stack'],[(0,1),(1,2),(1,3),(3,4)],y=y+20,cols=2,step=95)
y=cap('IoT level specification for the intended local home security installation',y)
para('Local operation requires disabled optional Supabase synchronization, preinstalled models and offline speech or prerecorded feedback. Edge TTS uses an online service. Enabling cloud services changes the deployment boundary. GPU capability alone does not establish an IoT level.',y,size=13);end()
title('7. Functional View Specification')
y=110
for t,col in [('Application<br/>Homeowner dashboard and assumed Android visitor interface','#dce9fa'),('Management<br/>Resident enrollment notices connection status and configuration','#e1f4e5'),('Services<br/>Media reception person detection face comparison alerts and intercom','#fff8cc'),('Communication<br/>Wi-Fi or USB ADB; SBMP TCP HTTP REST and WebSocket','#ece7fa'),('Device and resources<br/>Local host phone SQLite media files and proposed sensors and lamp','#fae1e1')]:box(t,78,y,440,62,col);y+=78
y=cap('Functional view specification for AI and CV Powered Home Security System',y)
para('The phone captures inputs and renders feedback. The host owns vision decisions, persistence and application services. OpenCV handles image processing; YOLO11 detects persons; InsightFace compares face embeddings. The local host is a single point of failure, requiring visible connection and frame-freshness status.',y,size=13);end()
y=title('8. Operational View Specification')
for a,b in [('Devices','Android endpoint, local AI computer and homeowner browser; proposed USB controller, IR presence sensor, proximity sensor and lamp.'),('Communication Protocols','IEEE 802.11 LAN or USB ADB transport; SBMP TCP port 9000; HTTP and WebSocket port 8000.'),('Services','Python FastAPI and a separate inference worker; local SQLite and media storage.'),('Application','HTML, CSS and JavaScript dashboard with enrollment, events, notices, kiosk mirror and intercom.'),('Security','Local hosting alone does not provide authentication. Restrict access to APIs, biometric files and media; browser microphone access may require trusted HTTPS.'),('Management','Check model loading, phone connection, frame freshness, battery, disk space and GPU resources. Back up database and media together.')]:
 y=para('<b>• '+a+':</b> '+b,y,75,463)
y=grid(['Application<br/>Browser dashboard','Services<br/>FastAPI and AI worker','Communication<br/>TCP HTTP WebSocket','Storage<br/>SQLite and media','Devices<br/>Phone and local host','Management<br/>Enrollment status backups'],[(0,1),(1,2),(2,3),(3,4)],y=y+8,step=80,h=48)
cap('Operational view specification',y);end()
y=title('9. Device and Component Integration')
y=grid(['Android endpoint<br/>Camera mic display speaker','Local AI computer<br/>USB ADB or Wi-Fi','Homeowner browser<br/>HTTP and WebSocket','IR presence sensor<br/>Proposed input','USB controller<br/>Proposed interface','Proximity sensor<br/>Proposed input','Rated low-voltage supply','MOSFET lamp driver<br/>Proposed output stage','Diffuse LED lamp<br/>Doorway illumination'],[(0,1),(1,2),(3,4),(4,7),(6,7),(7,8)],y=105,step=85,h=48)
y=cap('Component connection diagram for the home security system',y)
y=table([['Connection','Interface and status'],['Phone to host','TCP over Wi-Fi or USB ADB; assumed Android client'],['Browser to host','HTTP REST and WebSocket; supplied dashboard'],['Sensors to controller','Digital or I2C interface; module selection pending'],['Controller to host','Proposed USB serial link; firmware pending'],['Controller to lamp driver','Proposed control output; rated separate lamp supply']],y)
y=para('1. Android Camera and Audio Endpoint',y,bold=True)
y=para('Supplies the doorway camera, microphone, screen and speaker. Capture, notices and audio playback follow the assumed Android client contract. Camera modes, permissions and playback require client validation.',y)
y=para('2. Local AI Computer',y,bold=True)
para('Runs decoding, YOLO11, InsightFace, FastAPI and SQLite. The configured target is Ryzen 7 250, 32 GB DDR5 and RTX 5060 with 8 GB VRAM; actual capability requires verification.',y);end()
y=para('3. Display Microphone and Speaker',60,bold=True)
y=para('The phone screen or an HD display presents greetings and notices. The audio path uses 16 kHz mono 16-bit PCM in the assumed client contract. Test gain, echo, permissions and intelligibility in both directions.',y)
y=para('4. IR Presence and Proximity Sensors',y,bold=True)
y=para('Proposed presence sensing detects approach; a proximity module measures the interaction distance. Exact modules and electrical interfaces have not been selected. Debouncing, distance hysteresis, stale-reading rejection and reconnect handling require implementation.',y)
y=para('5. Lamp Driver and USB Controller',y,bold=True)
y=para('A proposed USB microcontroller bridges sensor signals and lamp commands because the computer has no assumed sensor GPIO. The host retains decision authority. A rated driver switches a separately powered low-voltage lamp; controller GPIO does not power the lamp directly.',y)
y=para('6. Integration and Validation',y,bold=True)
y=para('The component diagram is an integration plan, not an as-built pinout. Exact pins, logic voltages and supply ratings depend on the selected modules. Sensor firmware and lamp integration remain proposed. The software frame buffer holds up to 20 raw frames and does not provide continuous video archiving.',y)
para('Validate transport reconnects, frame age, multi-person tracking, face false matches, dwell alerts, phone feedback, storage recovery and offline behavior. No achieved frame rate, recognition accuracy or completed hardware acceptance is asserted.',y);end()
shot=Image.open(R/'report_work/new_template/dashboard.png')
def screenshot(crop,y,name,width=481):
 im=shot.crop(crop);p=W/(name+'.png');im.save(p);h=width*im.height/im.width;assert y+h<778;c.drawImage(str(p),57,842-y-h,width=width,height=h);return y+h+12
y=title('10. Application Development')
y=para('<b>1. Homeowner command center:</b> Shows the doorway feed, kiosk mirror, resident panel, security events, notices and intercom controls.',y)
y=screenshot((0,0,1440,1000),y+12,'overview')
y=para('Interface preview from the supplied dashboard source. The camera is waiting for a stream and records are not loaded. Displayed status labels and frame-rate values are interface values, not measured operating results.',y,size=12)
end()
y=para('<b>2. Camera monitoring and intercom:</b> The doorway camera panel provides snapshot and camera controls. The intercom provides microphone interaction and quick voice broadcasts.',60)
y=screenshot((24,85,610,925),y+12,'camera_audio',width=380)
para('Interface preview in the waiting state. Live video, microphone permissions, return playback and echo behavior require testing with the Android endpoint. Quick speech using Edge TTS requires Internet access.',y,size=12);end()
y=para('<b>3. Kiosk mirror and visitor notices:</b> The center panel mirrors the doorway interface and allows the homeowner to send text notices, request speech and trigger the siren command.',60)
y=screenshot((618,85,1013,878),y+12,'kiosk',width=270)
para('Interface preview. The illustrated kiosk screen is a placeholder rather than evidence of an active Android connection. Notices and audio are routed through the local host; client rendering and siren behavior require end-to-end validation.',y,size=12);end()
y=para('<b>4. Resident enrollment and event records:</b> Enrolled residents support local face comparison. The event panel presents security events and voice notes with filtering. Stored event media remain on the host.',60)
y=screenshot((1022,85,1420,388),y+12,'records')
y=para('Interface preview in an unpopulated state. Enrollment photos, event snapshots and transcripts appear after valid data are available; no sample recognition outcome is claimed.',y,size=12)
y=para('<b>Technology stack:</b> Frontend - HTML, CSS, JavaScript; Backend - Python FastAPI, Uvicorn, WebSockets; Vision - PyAV, OpenCV, YOLO11, InsightFace, ONNX Runtime GPU; Database - SQLAlchemy, aiosqlite, SQLite; transcription - Faster Whisper. Supabase sync is optional and excluded from the intended local deployment.',y)
y=para('<b>Implementation:</b> main.py serves the application; sbmp_server.py handles phone traffic; gpu_pipeline.py performs analysis; ring_buffer.py shares recent frames; models.py and database.py manage persistence.',y,size=12)
para('<b>Validation:</b> Test transport, fresh-frame rate and latency, identity and dwell behavior, intercom, notice delivery, restart persistence and offline operation. Android behavior is assumed and sensor integration remains proposed.',y,size=12);end()
c.save()
# Retain the reference cover, including its original logo and placement.
d=fitz.open(r'C:/Users/dushy/Downloads/PredictX_ESIOT_Report (2).pdf');cover=d[0]
for rect in [(60,231,535,280),(205,316,395,393),(90,442,510,462),(210,605,390,625)]:cover.add_redact_annot(fitz.Rect(rect),fill=(1,1,1))
cover.apply_redactions(images=0,graphics=0)
ov=BytesIO();cc=canvas.Canvas(ov,pagesize=(595.25,842))
def ct(t,y,font='T',size=14):cc.setFont(font,size);cc.drawCentredString(297.625,842-y,t)
ct('AI and CV Powered',249,'TB',20);ct('Home Security System',274,'TB',16)
for i,t in enumerate(['Dushyant Nanwatkar (41)','Shreya Nemane (42)','Arpita Nikam (43)','Arya Pagare (44)']):ct(t,330+i*19.1)
ct('Course Code: 2301306A      Course Name: Internet of Things',457,'TB',14)
ct('Academic Year 2026-27',620,'TB',14);cc.save();v=fitz.open(stream=ov.getvalue(),filetype='pdf');cover.show_pdf_page(cover.rect,v,0)
final=fitz.open();final.insert_pdf(d,from_page=0,to_page=0);final.insert_pdf(fitz.open(stream=B.getvalue(),filetype='pdf'));final.save(O,garbage=4,deflate=True)
for i,p in enumerate(final):p.get_pixmap(matrix=fitz.Matrix(1,1)).save(W/f'page-{i+1}.png')
print(O);print(len(final))


