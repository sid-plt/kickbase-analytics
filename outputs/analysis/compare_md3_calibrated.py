import ast, json, csv, re, unicodedata, statistics, math
from pathlib import Path
root=Path.cwd()
import sys
sys.path.insert(0,str(root))
from goalkeeper_kickbase_calibration import points_for_averages
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def norm(s): return re.sub('[^a-z0-9]','',unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower())
constants={}
for node in ast.parse((root/'sofascore_rating_odds_lineup_score.py').read_text(encoding='utf-8')).body:
 if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ['KB_TEAM_ID_TO_KEY','TEAM_ALIASES']: constants[node.targets[0].id]=ast.literal_eval(node.value)
alias={norm(n):k for k,v in constants['TEAM_ALIASES'].items() for n in v}
sp=max((root/'outputs/sofascore/player_kickbase_point_averages').glob('*.json')); kp=max((root/'outputs/kbstats/players').glob('*.json'))
s=read(sp); kb=read(kp); forms=next(iter(read(root/'outputs/sofascore/team_form'/s['source_file']).values()))
refs=list(csv.DictReader((root/'data/reference/player_name_cross_references.csv').open(encoding='utf-8-sig')))
rows=[]; unmatched=[]; used=set(); fixtures={}
for tid,t in s['teams'].items():
 teamkey=alias[norm(t['team'])]; fixture=max(forms[tid]['bundesliga_matches'],key=lambda x:x['timestamp']); assert fixture['date'][:10] in ['2026-09-11','2026-09-12','2026-09-13']; fixtures[fixture['match_id']]=fixture
 for p in t['overall']['players']:
  matches=[m for m in p['match_calculations'] if m['match_id']==fixture['match_id']]
  if not matches: continue
  assert len(matches)==1
  candidates=[k for k in kb if constants['KB_TEAM_ID_TO_KEY'][int(k['teamId'])]==teamkey and norm(k['name'])==norm(p['player_name'])]
  if not candidates:
   names={norm(r['kbstats_name']) for r in refs if r['provider']=='sofascore' and r['provider_player_id']==str(p['player_id'])}
   candidates=[k for k in kb if constants['KB_TEAM_ID_TO_KEY'][int(k['teamId'])]==teamkey and norm(k['name']) in names]
  if not candidates and p['player_id']==2650701:
   candidates=[k for k in kb if constants['KB_TEAM_ID_TO_KEY'][int(k['teamId'])]==teamkey and k['name']=='Rael-Tshimbela Nakuzola']
  if len(candidates)!=1: unmatched.append({'team':t['team'],'name':p['player_name'],'id':p['player_id']}); continue
  k=candidates[0]; used.add(k['id']); h=k['history'][0]; m=matches[0]; actual=h['points'] if h['hasPlayed'] else 0
  assert actual is not None
  assert sum(a['points'] for a in m['awards'])==m['calculated_kickbase_points']
  rows.append(dict(player=k['name'],team=t['team'],position=p['position'],kb_position={1:'GK',2:'DEF',3:'MID',4:'FWD'}[k['position']],sofascore=points_for_averages(m,p['position']),event_points=m['calculated_kickbase_points'],estimate=m.get('goalkeeper_residual_estimate'),kbstats=actual,difference=points_for_averages(m,p['position'])-actual,minutes=m['minutes_played'],kb_played=h['hasPlayed'],sofa_id=p['player_id'],kb_id=k['id'],match_id=m['match_id'],awards=m['awards']))
missing=[{'player':k['name'],'team':constants['KB_TEAM_ID_TO_KEY'][int(k['teamId'])],'points':k['history'][0]['points']} for k in kb if k['history'][0]['hasPlayed'] and k['id'] not in used]
rows.sort(key=lambda r:abs(r['difference']),reverse=True)
def stats(rr):
 ds=[r['difference'] for r in rr]; return dict(n=len(rr),bias=round(statistics.mean(ds),2),mae=round(statistics.mean(map(abs,ds)),2),rmse=round(math.sqrt(statistics.mean(d*d for d in ds)),2),exact=ds.count(0),over=sum(d>0 for d in ds),under=sum(d<0 for d in ds),within10=sum(abs(d)<=10 for d in ds),within25=sum(abs(d)<=25 for d in ds),over50=sum(abs(d)>50 for d in ds),sofa_total=sum(r['sofascore'] for r in rr),kb_total=sum(r['kbstats'] for r in rr))
result=dict(sofascore_source=str(sp),kbstats_source=str(kp),summary=stats(rows),by_position={p:stats([r for r in rows if r['position']==p]) for p in ['GK','DEF','MID','FWD']},by_team={t:stats([r for r in rows if r['team']==t]) for t in sorted(set(r['team'] for r in rows))},unmatched=unmatched,missing=missing,fixtures=list(fixtures.values()),rows=rows)
(root/'outputs/analysis/md3_sofascore_vs_kbstats_20260917.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result['summary']))
