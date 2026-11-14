from pathlib import Path
p=Path(__file__).with_name('build.py');s=p.read_text(encoding='utf-8-sig')
s=s.replace('[(0,1),(0,2),(0,3),(0,4),(0,5)]','[]')
s=s.replace('(3,4),(3,5),(5,6)','(3,4),(5,6)')
s=s.replace('Known resident?<br/>Compare enrolled embeddings','Compare enrolled faces<br/>Known or unknown result')
s=s.replace('Recognized<br/>Display greeting with cooldown','Known: display greeting<br/>with per-name cooldown')
s=s.replace('Unknown track<br/>Measure dwell duration','Unknown: measure dwell<br/>and apply warning rule')
s=s.replace('(3,4),(5,4),(4,7)','(3,4),(4,7)')
p.write_text(s,encoding='utf-8')
