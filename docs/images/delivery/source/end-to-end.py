"""Hand-positioned PawLocal architecture. Run with Python from any directory.
AWS service icons load from a pinned CDN into memory, then inline unchanged.
No graph/layout generator is used; viewing the generated artwork needs no network.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from icon_assets import load_icon

HERE = Path(__file__).resolve().parent
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
def tag(n): return "{" + NS + "}" + n
root = ET.Element(tag("svg"), {"width":"2000", "height":"1320", "viewBox":"0 0 2000 1320", "role":"img", "aria-labelledby":"architecture-title architecture-desc"})
ET.SubElement(root, tag("title"), {"id":"architecture-title"}).text = "PawLocal end-to-end application architecture"
ET.SubElement(root, tag("desc"), {"id":"architecture-desc"}).text = "Separate development and production AWS environments each contain CloudFront, S3, Cognito, a Lightsail FastAPI service and Aurora DSQL. Browser sessions call the matching HTTPS services. Browser Faro and API OTLP send telemetry directly to external Grafana Cloud. Local Compose uses PostgreSQL and a separate local observability stack. Environment boundaries are logical, not VPC or account claims."
N='#13243A'; MUT='#53657A'; TEAL='#007F78'; PUR='#7050A0'; ORANGE='#ED7D22'; GRAY='#617689'
def el(name, attrs, parent=root): return ET.SubElement(parent,tag(name),{k:str(v) for k,v in attrs.items()})
def rect(x,y,w,h,fill='white',stroke='#D9E2EA',r=12,sw=1.8):
 return el('rect',dict(x=x,y=y,width=w,height=h,rx=r,fill=fill,stroke=stroke,**{'stroke-width':sw}))
def text(x,y,value,size=24,color=N,weight=400):
 e=el('text',dict(x=x,y=y,fill=color,**{'font-family':'Segoe UI, Arial, sans-serif','font-size':size,'font-weight':weight})); e.text=value;return e
def line(d,color=GRAY,dash=False,arrow=True):
 a={'d':d,'fill':'none','stroke':color,'stroke-width':2.5,'stroke-linejoin':'round','stroke-linecap':'round'}
 if dash:a['stroke-dasharray']='7 6'
 if arrow:a['marker-end']='url(#arrow-'+('purple' if color==PUR else 'gray')+')'
 return el('path',a)
def label(x,y,value,color=MUT,size=22):
 text(x,y,value,size,color)

def icon(name,x,y,size=64,prefix='icon'):
 s=ET.fromstring(load_icon(name))
 ids={v.attrib['id']:prefix+'-'+re.sub('[^a-zA-Z0-9_-]','-',v.attrib['id']) for v in s.iter() if 'id' in v.attrib}
 for v in s.iter():
  for k,value in list(v.attrib.items()):
   if k=='id':v.set(k,ids[value])
   else:
    for old,new in ids.items():value=value.replace('url(#'+old+')','url(#'+new+')').replace('#'+old,'#'+new)
    v.set(k,value)
 s.set('x',str(x));s.set('y',str(y));s.set('width',str(size));s.set('height',str(size));s.set('preserveAspectRatio','xMidYMid meet')
 root.append(s)

def service(x,y,w,name,subtitle,filename,prefix):
 rect(x,y,w,100,'#FFFFFF','#D9E2EA',10)
 icon(filename,x+16,y+18,64,prefix)
 text(x+94,y+40,name,24,N,600)
 text(x+94,y+73,subtitle,22,MUT)

rect(0,0,2000,1320,'#FFFFFF','none',0)
text(60,73,'PawLocal',48,N,700)
text(295,73,'End-to-end architecture',39,N,400)
text(60,118,'Discover a place → inspect details → save, contribute and report',25,MUT)
# Key sits at the far right without competing with the title.
line('M 1390 76 H 1445',GRAY);text(1460,83,'Application path',22,MUT)
line('M 1695 76 H 1750',PUR,True);text(1765,83,'Telemetry',22,MUT)
# Outer surfaces: environment boundaries are deliberately logical, not network topology.
rect(400,195,1120,800,'#FFFBF5','#E8A155',18,2.2)
text(430,231,'AWS',26,ORANGE,700)
text(505,231,'Logical environment isolation',23,MUT)
rect(430,255,1060,300,'#FFFFFF','#CBD8E4',13,2)
text(450,291,'DEVELOPMENT',24,TEAL,700)
text(1095,291,'Independent application state',22,MUT)
rect(430,595,1060,300,'#FFFFFF','#CBD8E4',13,2)
text(450,631,'PRODUCTION',24,'#2463A6',700)
text(1095,631,'Independent application state',22,MUT)
# Browser surface and two sessions make direct environment selection explicit.
rect(60,255,280,640,'#F1F9F8','#65AAA8',15,2)
text(82,293,'Browser sessions',27,TEAL,700)
icon('react.svg',82,304,26,'browser-react')
text(118,326,'React · TS · Vite',22,MUT)
for y,env in [(354,'Development'),(694,'Production')]:
 rect(82,y,236,144,'#FFFFFF','#BDDAD7',10)
 text(102,y+34,env,23,TEAL if env=='Development' else '#2463A6',600)
 text(102,y+70,'Browse / search / detail',22,N)
 text(102,y+104,'Typed HTTP services',22,N)
# AWS service cards and their intentionally fixed orthogonal connection routes.
for dy,prefix in [(0,'dev'),(340,'prod')]:
 y=325+dy
 service(450,y,245,'CloudFront','HTTPS frontend','Arch_Amazon-CloudFront_64.svg',prefix+'-cf')
 service(780,y,260,'Amazon S3','Frontend assets','Arch_Amazon-Simple-Storage-Service_64.svg',prefix+'-s3')
 service(1200,y,270,'Cognito','Sign-in / PKCE','Arch_Amazon-Cognito_64.svg',prefix+'-auth')
 service(780,y+120,290,'Lightsail','FastAPI service','Arch_Amazon-Lightsail_64.svg',prefix+'-api')
 service(1200,y+120,270,'Aurora DSQL','App persistence','Arch_Amazon-Aurora_64.svg',prefix+'-db')
 line(f'M 340 {y+17} H 365 V {y-15} H 1335 V {y}',GRAY,True)
 line(f'M 340 {y+40} H 450')
 line(f'M 695 {y+50} H 780')
 label(705,y+28,'Assets',size=22)
 line(f'M 340 {y+170} H 780')
 label(460,y+158,'HTTPS API · token for writes',size=22)
 line(f'M 1070 {y+170} H 1200')
 label(1090,y+153,'TLS SQL',size=22)
 # Backend verifies Cognito JWTs; browser sign-in remains labelled on Cognito.
 line(f'M 1060 {y+120} V {y+70} H 1200',GRAY,True)
 label(1072,y+53,'JWT / JWKS',size=22)
 # Export lines leave below cards, avoiding data/auth connectors.
 line(f'M 970 {y+220} V {y+229} H 1550 V 570 H 1590',PUR,True)
# Credential ownership band inside AWS. It describes two scoped copies, never a shared identity.
icon('Arch_AWS-Identity-and-Access-Management_64.svg',450,924,48,'runtime-iam')
icon('Arch_AWS-Systems-Manager_64.svg',515,924,48,'runtime-ssm')
text(590,942,'Per environment: scoped runtime IAM role + Parameter Store',24,N,600)
text(590,974,'Short-lived DSQL credentials · server-only OTLP token · config injected at deploy',22,MUT)
# External Grafana: direct browser and backend transport, no implied cloud Collector.
rect(1590,255,350,640,'#F8F4FC','#A58BC5',15,2)
icon('grafana.svg',1616,270,32,'grafana-brand')
text(1662,295,'Grafana Cloud',29,PUR,700)
text(1616,328,'External hosted observability',22,MUT)
rect(1614,365,302,112,'#FFFFFF','#CEBEDF',10)
text(1635,403,'Faro',27,PUR,600)
text(1635,437,'Browser journey signals',22,N)
rect(1614,520,302,145,'#FFFFFF','#CEBEDF',10)
text(1635,557,'Direct OTLP',27,PUR,600)
text(1635,593,'Metrics / structured logs',22,N)
text(1635,627,'Sampled correlated traces',22,N)
rect(1614,718,302,137,'#FFFFFF','#CEBEDF',10)
text(1635,757,'Dashboards + alerts',26,PUR,600)
text(1635,792,'Search → API → database',22,N)
text(1635,827,'User-impact indicators',22,N)
line('M 1640 477 V 495 H 1603 V 695 H 1640 V 718',PUR,True)
line('M 1765 665 V 718',PUR,True)
line('M 200 255 V 170 H 1565 V 420 H 1614',PUR,True)
label(1110,158,'Privacy-bounded browser telemetry',PUR,23)
label(1558,505,'',PUR)
# Direct OTLP label sits on a white gap below AWS rows instead of on service cards.
text(1618,880,'Environment + release labels',22,MUT)
# Local lane is intentionally separate from both hosted environments.
rect(60,1040,1880,205,'#F6F9FC','#C4D2DF',15,2)
icon('docker.svg',85,1053,36,'local-docker')
text(135,1081,'LOCAL COMPOSE',25,TEAL,700)
text(405,1081,'Separate reproducible stack · no cloud provisioning',23,MUT)
rect(85,1110,420,104,'#FFFFFF','#BCD9D7',10)
text(108,1149,'Browser → React → FastAPI',26,TEAL,600)
text(108,1186,'HTTP adapter / same-origin API proxy',22,MUT)
rect(605,1110,365,104,'#FFFFFF','#C4D2DF',10)
text(630,1149,'PostgreSQL',26,N,600)
text(630,1186,'SQLAlchemy / Alembic',23,MUT)
line('M 505 1162 H 605')
rect(1110,1110,805,104,'#FFFFFF','#CEBEDF',10)
text(1135,1149,'OpenTelemetry Collector → Prometheus / Loki / Tempo',25,PUR,600)
text(1135,1186,'Local Grafana dashboards · local metrics, logs and traces',23,MUT)
line('M 505 1195 H 550 V 1230 H 1060 V 1162 H 1110',PUR,True)
text(60,1290,'Service boundaries show logical ownership; no VPC, subnet, account isolation or HA topology is implied.',22,MUT)
# Arrowheads are defined once; official icon IDs are prefixed per instance.
defs=el('defs',{})
for name,color in [('gray',GRAY),('purple',PUR)]:
 m=el('marker',{'id':'arrow-'+name,'viewBox':'0 0 10 10','refX':9,'refY':5,'markerWidth':8,'markerHeight':8,'orient':'auto-start-reverse'},defs)
 el('path',{'d':'M 1 1 L 9 5 L 1 9 z','fill':color},m)
out=HERE.parent/'architecture-end-to-end.svg'
ET.indent(root,space='  ')
ET.ElementTree(root).write(out,encoding='utf-8',xml_declaration=True)
print(out)
