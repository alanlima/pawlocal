"""Hand-positioned SVG. No diagram/layout engine. Official AWS icons are inline."""
from pathlib import Path
from html import escape
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT/'docs/images/delivery/architecture-operations-cicd.svg'
ICONS = ROOT/'docs/images/delivery/source/icons'
parts=[]
def add(s): parts.append(s)
def rect(x,y,w,h,fill='#ffffff',stroke='#d8e1ec',r=16): add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}"/>')
def text(x,y,s,size=20,weight=400,color='#13243A',anchor='start'):
 add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{escape(s)}</text>')
def lines(x,y,ss,size=19,gap=28,color='#53657A'):
 for i,s in enumerate(ss):text(x,y+i*gap,s,size,color=color)
def arrow(d,color='#607990',dash=False):add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.7" stroke-linejoin="round" {chr(32)+"stroke-dasharray=\"7 6\"" if dash else ""} marker-end="url(#arrow)"/>')
def icon(name,x,y,size=48):
 f=next(p for p in ICONS.glob('*.svg') if name in p.name and not p.name.startswith('._'))
 e=ET.fromstring(f.read_bytes());e.set('x',str(x));e.set('y',str(y));e.set('width',str(size));e.set('height',str(size))
 # All bundled service icons used here are self-contained path geometry.
 for el in e.iter():
  if 'id' in el.attrib:el.set('id','aws-'+name+'-'+el.get('id').replace('/','-'))
 add(ET.tostring(e,encoding='unicode'))
def generic(kind,x,y):
 rect(x,y,46,46,'#edf2f8','#cdd9e7',10)
 if kind=='git':
  add(f'<path d="M{x+15} {y+12}v22 M{x+15} {y+25}q17 0 17-13" fill="none" stroke="#476788" stroke-width="2.5"/>')
  for cx,cy in [(15,12),(15,34),(32,12)]:add(f'<circle cx="{x+cx}" cy="{y+cy}" r="4" fill="#476788"/>')
 elif kind=='package':
  add(f'<path d="M{x+10} {y+15}l13-7 13 7v17l-13 7-13-7z M{x+10} {y+15}l13 7 13-7 M{x+23} {y+22}v17" fill="none" stroke="#476788" stroke-width="2.2"/>')
 else:text(x+23,y+30,{'tf':'TF','check':'✓','model':'AI','chart':'↗','ops':'OP'}.get(kind,kind),18,700,anchor='middle')
def stage(x,y,num,title,sub):
 add(f'<circle cx="{x+17}" cy="{y+17}" r="17" fill="#193b63"/>');text(x+17,y+23,str(num),17,700,'#ffffff','middle');text(x+45,y+24,title,23,700);text(x+45,y+51,sub,16,color='#63758c')
add('<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1400" viewBox="0 0 2000 1400" role="img" aria-labelledby="title desc">')
add('<title id="title">PawLocal operations and CI/CD architecture</title><desc id="desc">Ordinary owner-approved changes and mode-dependent incident automation share immutable development and production releases, with separate Terraform states and recovery assessment.</desc>')
add('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#607990"/></marker></defs>')
add('<g font-family="Segoe UI, Arial, sans-serif">');rect(0,0,2000,1400,'#f7f9fc','#f7f9fc',0)
text(60,65,'PawLocal',22,700,'#436d64');text(60,112,'Operations & release architecture',40,700)
text(1940,74,'IMPLEMENTED CAPABILITIES',15,700,'#60758d','end');text(1940,105,'Evidence and policy limits remain separate',18,color='#60758d',anchor='end')
# GitHub control plane
rect(50,148,1900,300,'#edf2f9','#cbd9e9',22);text(76,183,'GITHUB  /  SOURCE, AUTHORIZATION & RELEASE AUTOMATION',16,700,'#2463A6')
rect(78,209,320,208);icon('github',326,231,46);stage(98,229,1,'Change','Issue / scoped branch')
lines(98,329,['Pull request','Approved, scoped work'],21,32)
rect(435,209,450,208);stage(455,229,2,'Checks & authorization','Applicable CI; external GitHub rules')
lines(455,321,['Ordinary: protected owner approval','Incident: review / authorization policies','follow the resolved enforcement mode'],21,31)
rect(925,209,300,208);generic('check',945,231);text(945,312,'Squash merge',23,700);lines(945,353,['Ordinary: owner','Incident: trusted job'],21,31)
rect(1265,209,655,208);generic('package',1287,231);stage(1350,229,3,'Build on main','Frontend + backend release checks')
lines(1288,335,['Publish immutable backend image to GHCR','Bind release source commit and image digest'],21,33);text(1288,399,'Trusted publication / release jobs: scoped credentials',18,600,'#53657A')
arrow('M398 314 H435');arrow('M885 314 H925');arrow('M1225 314 H1265')
# Release platform boundaries
rect(50,478,350,422,'#fff8f0','#ED7D22',22);text(76,515,'AWS  /  IAM BOOTSTRAP',16,700,'#2463A6');icon('Identity-and-Access',78,542,60)
text(76,641,'Separate Terraform state',22,700);lines(76,689,['Deployment identities','Trust / policy boundaries','Reviewed setup / handoffs'],21,34)
text(76,846,'No shared application state',17,600,'#63758c')
rect(445,478,620,422,'#eef7f4','#b9d7d2',22);text(471,515,'AWS  /  DEVELOPMENT',16,700,'#007F78');icon('terraform',471,541,46);stage(535,541,4,'Deploy & verify','Development application Terraform state')
lines(471,648,['Exact saved-plan apply','Build / publish development frontend','Verify served release, API and database'],21,35)
rect(471,775,568,96,'#ffffff','#b9d7d2',12);text(493,811,'VERIFIED DEVELOPMENT EVIDENCE',15,700,'#007F78');text(493,844,'Same source commit + backend image digest',20,600)
# routes
rect(1095,562,170,119,'#ffffff','#d5deea',13);text(1180,595,'ORDINARY',14,700,'#526c87','middle');text(1180,625,'Manual dispatch',20,600,anchor='middle');text(1180,653,'Owner approvals',19,anchor='middle')
rect(1095,725,170,126,'#f6f1fb','#d7cce6',13);text(1180,758,'INCIDENT',14,700,'#7050A0','middle');text(1180,789,'Auto promoter',20,600,anchor='middle');text(1180,819,'Mode-dependent',18,anchor='middle')
rect(1295,478,655,422,'#eef2fa','#c7d4e7',22);text(1321,515,'AWS  /  PRODUCTION',16,700,'#2463A6');icon('terraform',1321,541,46);stage(1385,541,5,'Promote & verify','Production application Terraform state')
lines(1321,648,['Select the DEV-verified source and image','Exact saved-plan apply','REBUILD frontend with production configuration','Publish; verify served release, API and database'],20,35)
rect(1321,819,603,52,'#ffffff','#c7d4e7',10);text(1342,852,'Deployment success ≠ accepted incident recovery',20,600)
arrow('M1590 417 V465 H755 V478');arrow('M400 686 H445','#8494a8',True)
# boot to production, over platform top edge
text(76,792,'Roles serve DEV + PROD',20,600,'#53657A')
arrow('M1039 804 H1075 V622 H1095');arrow('M1265 622 H1295');arrow('M1039 844 H1087 V792 H1095');arrow('M1265 792 H1295')
text(1095,535,'RELEASE ROUTES',13,700,'#63758c')
# incident zone
rect(50,938,1900,292,'#f5f1fa','#d9cfe6',22);text(76,973,'OBSERVABILITY & INCIDENT RESPONSE  /  SEPARATE RUNTIME BOUNDARIES',16,700,'#7050A0')
rect(78,998,335,201);icon('grafana',98,1019,46);text(98,1100,'Grafana Cloud',23,700);lines(98,1136,['Journey signals / dashboards','User-impact firing alert'],21,31)
rect(461,998,315,201);icon('AWS-Lambda',482,1018,49);text(482,1100,'AWS Lambda receiver',22,700);lines(482,1136,['HMAC webhook','Lambda Function URL'],21,31)
rect(824,998,486,201);generic('model',845,1019);text(906,1048,'Model & test isolation',22,700);lines(845,1096,['Fixer → tests → fresh reviewer','No publication / deploy credentials','Review policies are mode-dependent'],21,32)
rect(1358,998,566,201);text(1380,1048,'Recovery assessment & outcome',24,700);lines(1380,1097,['Controller observes release + original journey','Records verified or unverified outcome','A green deploy is not recovery acceptance'],20,32)
arrow('M413 1091 H461');arrow('M776 1091 H824');arrow('M1620 900 V998');text(1640,958,'Incident only',18,600,'#53657A')
# Incident returns to PR outside left boundary, never through release credentials
# telemetry to Grafana, routed between rows
arrow('M1830 900 V913 H245 V998','#806a9b',True)
arrow('M1067 998 V930 H257 Q245 914 233 930 H28 V309 H78','#806a9b',True)
add('<text x="18" y="790" transform="rotate(-90 18 790)" font-size="16" fill="#7050A0">Incident candidate to PR</text>')
# signals also inform outcome; separate dashed path below cards
arrow('M245 1199 V1214 H1640 V1199','#806a9b',True)
# policy footer
rect(50,1250,1900,116,'#fff9eb','#e5d4a5',16);text(76,1284,'CURRENT POLICY LIMITS',15,700,'#886a2d')
text(76,1316,'DEC-017: incident software review, provenance, budget, stop and recovery checks can be skipped. External GitHub / IAM controls remain.',19)
text(76,1346,'DEC-015: strict release-only validator is off. Models remain isolated before merge; merged operational code may run in credential-bearing release jobs.',18)
text(1940,1388,'Operator runbooks: investigate · emergency stop · recovery review  |  No new infrastructure approval implied',16,color='#63758c',anchor='end')
add('</g></svg>');OUT.write_text(''.join(parts),encoding='utf-8');ET.fromstring(OUT.read_bytes())
print(OUT)
