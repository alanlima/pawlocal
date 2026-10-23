from pathlib import Path
from html import escape
import base64
ROOT=Path(__file__).resolve().parent
W=2200
parts=[]
def text(x,y,s,size=23,fill='#23344a',weight=400):
 parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}">{escape(s)}</text>')
def rect(x,y,w,h,fill,stroke='none',r=18):
 parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}"/>')
def icon(name,x,y,size=52):
 p=ROOT/'icons'/name
 mime='image/png' if p.suffix=='.png' else 'image/svg+xml'
 b=base64.b64encode(p.read_bytes()).decode()
 parts.append(f'<image x="{x}" y="{y}" width="{size}" height="{size}" href="data:{mime};base64,{b}"/>')
def line(x1,y1,x2,y2,label=None,color='#60758d'):
 parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}" stroke-width="3" fill="none" marker-end="url(#arrow)"/>')
 if label:
  mx=(x1+x2)/2;my=(y1+y2)/2
  rect(mx-24,my-20,48,36,'#f1f5fa',r=18);text(mx,my+6,label,19,color,700)
def card(x,y,title,subtitle,lines,icons,color='#237b9c',h=240):
 rect(x,y,640,h,'#ffffff','#cbd7e4')
 rect(x,y,7,h,color,r=3)
 for j,ic in enumerate(icons):icon(ic,x+24+j*62,y+20,48)
 titlex=x+24+len(icons)*62
 text(titlex,y+42,title,25,'#102a44',700)
 text(x+24,y+94,subtitle,20,color,600)
 for i,s in enumerate(lines):text(x+24,y+132+i*29,s,22)
def begin(height,title,subtitle):
 parts.clear();parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="2200" height="{height}" viewBox="0 0 2200 {height}" role="img" aria-label="{escape(title)}"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10Z" fill="#60758d"/></marker></defs><g font-family="Segoe UI,Arial,sans-serif">')
 rect(0,0,2200,height,'#f1f5fa',r=0)
 rect(0,0,2200,172,'#10243a',r=0)
 text(64,65,title,41,'#ffffff',700);text(64,110,subtitle,24,'#b8cce3')
 text(64,145,'GROOMING PROPOSAL  |  23 OCT 2026  |  #59 OBSERVABILITY → #42 INCIDENT RESPONSE',20,'#76d2ca',600)
def save(name):
 parts.append('</g></svg>');(ROOT/name).write_text('\n'.join(parts),encoding='utf-8')

begin(1850,'PawLocal · Simple cloud monitoring & assisted recovery','Grafana Cloud Free → one AWS Lambda → GitHub-hosted agents → protected existing releases')
text(64,213,'PROPOSED RESOURCE & WORKFLOW DESIGN',20,'#61758b',700)
text(760,213,'<env> = development | production. Named functions and workflows are proposed.',22)
x=[64,780,1496];y=[246,596,946]
card(x[0],y[0],'Hosted PawLocal','DIRECT TELEMETRY · NO CUSTOM RELAY',[
 'React: Grafana Faro → hosted frontend intake','FastAPI: direct OTLP → Grafana Cloud','Private backend ingestion token stays server-side','Existing Lightsail / CloudFront / Aurora DSQL'],['Amazon-Lightsail.svg','Amazon-CloudFront.svg'],h=260)
card(x[1],y[0],'Grafana Cloud Free','MANAGED METRICS + LOKI LOGS + TEMPO TRACES',[
 '10k metric series · 50 GB logs · 50 GB traces','14-day retention; sample / redact / limit labels','Journey dashboards + external synthetic checks','Signed firing / resolved HTTPS notifications'],['grafana.svg'],color='#d77a22',h=260)
card(x[2],y[0],'One webhook function','LAMBDA FUNCTION URL · PUBLIC HTTPS',[
 'pawlocal-<env>-oncall-receiver','Verify HMAC + timestamp + allowlisted labels','Forward validated workflow_dispatch to GitHub','Return 204 only after dispatch is accepted'],['AWS-Lambda.svg'],h=260)
line(704,376,780,376,'1');line(1420,376,1496,376,'2');line(1816,506,1816,596,'3')
card(x[2],y[1],'GitHub workflow intake','PROPOSED · incident-responder.yml',[
 'GitHub-hosted Ubuntu runner; fixed workflow ref','Fingerprint / generation + issue / PR dedupe','Serialized concurrency; check current alert state','One active incident run; finite 20-minute budget'],['github.png'],color='#7256a6',h=260)
card(x[1],y[1],'Codex fixer job','INDEPENDENT OPENAI API CALL · STANDARD',[
 'gpt-6.1-sol · medium reasoning','Reproduce affected release → test → patch','One coding attempt; redacted telemetry tools','Isolated runner; no production credentials'],['github.png'],color='#7256a6',h=260)
card(x[0],y[1],'Fresh reviewer job','INDEPENDENT OPENAI API CALL · STANDARD',[
 'gpt-6.1-sol · medium reasoning','New context; review pinned patch / candidate','Re-run tests; findings → escalate or publish','No self-approval, merge or deployment tools'],['github.png'],color='#7256a6',h=260)
line(1496,726,1420,726,'4');line(780,726,704,726,'5');line(384,856,384,946,'6')
card(x[0],y[2],'Publish PR / human gate','TRUSTED JOB · FIXED VALIDATION + GITHUB APP',[
 'Validate base SHA / paths / patch / test evidence','Link incident issue + independent review report','Required CI + human review → squash merge','Model output never controls publisher credentials'],['github.png'],color='#b17d21',h=260)
card(x[1],y[2],'Development release','EXISTING · fullstack-release.yml',[
 'Approved merge → immutable GHCR artifact','Existing Terraform-owned Lightsail deployment','Smoke + original regression + public journey','Record verified release SHA / image digest'],['github.png','Amazon-Lightsail.svg'],h=260)
card(x[2],y[2],'Production promotion','EXISTING · deploy-production.yml',[
 'Human workflow_dispatch + protected approval','Select exact development-verified release','Reviewed plan → Terraform-owned deployment','Smoke / public journey / recovery observation'],['github.png','Amazon-Lightsail.svg'],color='#b17d21',h=260)
line(704,1076,780,1076,'7');line(1420,1076,1496,1076,'8');line(1816,1206,1816,1270,'9')
rect(64,1270,2072,100,'#def2ea','#92c5ae')
text(90,1309,'RECOVERY IS VERIFIED EVIDENCE',25,'#175b42',700)
text(90,1346,'Healthy journey + original regression + resolved alert + observation window → close incident. Otherwise escalate to owner.',24,'#175b42')
rect(64,1394,2072,236,'#e6ecf4','#cbd7e4')
text(90,1434,'SUPPORTING INTEGRATIONS / FINITE EXECUTION',23,'#304c6b',700)
for xx,ic,title,label in [(90,'AWS-Systems-Manager.svg','SSM config + SecureString','Exact-key access; server-only token / HMAC'),(780,'Amazon-CloudWatch.svg','CloudWatch (optional)','Read-only Grafana data source queries'),(1496,'github.png','GitHub App + OpenAI API','Trusted publisher; separate API funding')]:
 icon(ic,xx,1454,44);text(xx+58,1474,title,22,'#203b58',700);text(xx,1520,label,20)
text(90,1564,'20-minute TOTAL run deadline · 1 coding attempt · 1 active run · $20/month planning budget is not a hard spending cap.',23)
text(90,1604,'Example aggregate model use: 200k input + 20k output tokens ≈ $0.60/incident; 20 incidents ≈ $12 (both calls included).',22)
text(64,1678,'RESOURCE SCOPE  One function per enabled environment, plus URL, least-privilege role, exact SSM access and finite CloudWatch Logs.',22,'#4a607a')
text(64,1714,'OWNERSHIP  Existing bootstrap / development / production states only. Terraform publishes non-secret Strings; secret payloads stay outside state.',22,'#4a607a')
text(64,1750,'DELIVERY LIMIT  GitHub concurrency is not a durable queue or exactly-once delivery. Dispatch retries + issue / PR identity need acceptance tests.',22,'#4a607a')
text(64,1786,'GATES  G1 before live responder wiring. #42 needs endpoint ownership and durability-acceptance amendments before affected live activation / acceptance.',22,'#4a607a')
text(64,1822,'METRICS  Optional CloudWatch queries do not require forwarding / Firehose. Grafana stack isolation and actual quota consumption remain gates.',21,'#4a607a')
save('stage5-monitoring-cloud-agent.svg')

begin(1430,'PawLocal · Incident & agent lifecycle','Direct telemetry + one authenticated webhook function + GitHub-hosted jobs • finite cloud execution')
steps=[('01','OBSERVE','React Faro / FastAPI OTLP → Grafana Cloud','Correlate journey, environment and deployed release.'),('02','RECEIVE','Signed firing / resolved alert → Function URL','Authenticate HMAC / timestamp; allowlist payload.'),('03','DISPATCH','Lambda → GitHub workflow_dispatch','204 only after accepted dispatch; reject on failure.'),('04','VALIDATE / DEDUPE','GitHub workflow: issue fingerprint + generation','Serialize runs; dedupe PR; check current alert state.'),('05','FIX','Codex action · gpt-6.1-sol / medium / Standard','Reproduce affected release; regression test; patch.'),('06','INDEPENDENT REVIEW','Fresh Codex call · same model / effort / tier','New context; pinned candidate; isolated tests.'),('07','PUBLISH PR','Trusted job validates patch and base identity','GitHub App credential isolated from agent jobs.'),('08','HUMAN REVIEW / MERGE','Required CI + owner approval → squash merge','Agent report cannot replace required human review.'),('09','VERIFY DEVELOPMENT','Existing fullstack-release.yml → live checks','Deploy immutable release; verify original regression.'),('10','HUMAN PRODUCTION GATE','Existing deploy-production.yml + protection','Promote exact development-verified SHA / artifact.'),('11','VERIFY RECOVERY','External journey + telemetry + regression','Observe recovery window; resolved alone is insufficient.'),('12','CLOSE OR ESCALATE','GitHub incident issue + evidence + owner','Record release identity; failed attempts escalate.')]
for i,(num,title,resource,detail) in enumerate(steps):
 col=i//6;row=i%6;xx=64+col*1070;yy=220+row*155
 rect(xx,yy,1010,128,'#ffffff','#ccd8e6');rect(xx+20,yy+22,62,62,'#dceaf6',r=31);text(xx+33,yy+63,num,27,'#275c86',700)
 text(xx+104,yy+36,title,23,'#214665',700);text(xx+104,yy+73,resource,23);text(xx+104,yy+108,detail,21,'#52677f')
 if row<5:line(xx+51,yy+128,xx+51,yy+155)
rect(64,1170,2072,184,'#fff0d6','#dfbe80')
text(90,1212,'BOUNDED ATTEMPT / EXPLICIT DELIVERY LIMITS',26,'#755017',700)
text(90,1252,'One active run, one coding attempt, 20-minute total deadline. Timeout, stale alert, failed tests or review findings → owner.',24)
text(90,1292,'Fingerprint / generation and current-alert checks reduce duplicate work; GitHub serialization is not durable queueing or exactly-once execution.',23)
text(90,1330,'Resolved alerts update incident state; current state is checked before coding and publishing. Test dispatch-loss / retry / duplicate behavior.',23)
text(64,1400,'AWS Lambda receives alerts; GitHub hosts the agents. No long-running agent server, production credentials in agent jobs or automatic production approval.',22,'#4a607a')
save('stage5-monitoring-agent-lifecycle.svg')

begin(1500,'PawLocal · Implementation sequence & gates','Ten issue-linked packages • implementation authorized; live applies and activation require their recorded gates')
waves=[
 ('1','SPECIFY / RECONCILE READINESS','P0 #222','Approved architecture, exact sources, contracts, current readiness and review evidence.','Open #43 is not acceptance evidence; unmerged PR #182 does not silently renumber stages.','github.png'),
 ('2','CONFIGURE / PROVISION GRAFANA','P1 #223 + P2 #224 ← P0','P1: minimal mapping + on-call target allowlist + scoped SSM/KMS/trust.','P2: reproducible Grafana account/region/Free provisioning + actual endpoint settings.','AWS-Systems-Manager.svg'),
 ('3','ENABLE DIRECT TELEMETRY','P3 #225 ← P1 + P2','FastAPI OTLP + React Faro; runtime-only token; privacy and bounded fail-open export.','Coordinate release flags, public build snapshots, manifests and evidence validators.','grafana.svg'),
 ('4','ACCEPT MONITORING / G1','P4 #226 ← P3','Six reproducible dashboards + one synthetic journey alert; quotas / isolation / disable proof.','G1 gates live responder wiring. P8 production monitoring can start after G1 with separate approval.','grafana.svg'),
 ('5','IMPLEMENT CLOUD RESPONSE','P5 #227 + P6 #228','P5 Lambda intake depends on P1. P6 GitHub fixer/review/publisher needs P1 + P5 schema.','Mocks can develop in parallel; exact HMAC/dispatch boundary + isolated trusted publication.','AWS-Lambda.svg'),
 ('6','ACCEPT DEVELOPMENT REPAIR / G2','P7 #229 ← P4 + P5 + P6','Alert → regression → fix → independent report → PR → human merge → verified recovery.','Prove duplicates, stale/resolved races, dispatch loss, failed review, timeout and escalation.','github.png'),
 ('7','OBSERVE PROD / HUMAN PROMOTION','P8 #230 → P9 #231','P8 monitoring depends on P4/G1. P9 triage + human promotion depends on P7/G2 + P8.','Explicit production-read approval; exact dev-verified release; manual protected promotion.','Amazon-Lightsail.svg')]
for i,(num,title,seq,detail,note,ic) in enumerate(waves):
 yy=216+i*162
 rect(64,yy,2072,136,'#ffffff','#ccd8e6');icon(ic,88,yy+25,54)
 text(168,yy+36,f'{num}  {title}',23,'#215876',700);text(1200,yy+36,seq,24,'#215876',700)
 text(168,yy+77,detail,23);text(168,yy+111,note,22,'#52677f')
 if i<6:line(116,yy+136,116,yy+162)
text(64,1394,'CODE / APPLY / ACTIVATION ARE SEPARATE MILESTONES',25,'#755017',700)
text(64,1435,'Every package needs its scoped issue, PR, tests and independent review. Billable applies need explicit approval; secret payloads stay outside Terraform state.',22)
text(64,1473,'G1 / G2 are acceptance gates. Human merge and protected manual production promotion remain required throughout.',22,'#52677f')
save('stage5-monitoring-implementation-sequence.svg')
