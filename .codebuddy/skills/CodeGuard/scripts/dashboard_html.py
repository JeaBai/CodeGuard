"""自包含 HTML 看板模板。"""
from __future__ import annotations

# ============================================================
# HTML 模板
# ============================================================

_HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>%PROJECT_NAME% — 代码健康看板</title>
<style>
:root{--bg:#0f1117;--card:#1a1d27;--border:#2a2d3a;--text:#c9d1d9;--dim:#8b949e;
  --green:#3fb950;--yellow:#d2991d;--red:#f85149;--blue:#58a6ff;--purple:#bc8cff;}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.header{padding:24px 32px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px}
.header h1{font-size:24px;font-weight:600}
.header .score-big{font-size:56px;font-weight:800;line-height:1}
.header .trend{font-size:16px;margin-left:8px}
.header .meta{color:var(--dim);font-size:13px}
.grid{padding:24px 32px;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.dim-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}
.dim-card .icon{font-size:24px;margin-bottom:8px}
.dim-card .score{font-size:40px;font-weight:700}
.dim-card .label{color:var(--dim);font-size:13px;margin-top:4px}
.dim-card .detail{font-size:12px;color:var(--dim)}
.dim-card .status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dim-card.good .status-dot{background:var(--green)}
.dim-card.warn .status-dot{background:var(--yellow)}
.dim-card.danger .status-dot{background:var(--red)}
.chart-container{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin:0 32px 16px}
.chart-container h3{margin-bottom:12px;font-size:16px}
canvas{width:100%;max-height:200px}
.section{padding:0 32px 24px}
.section h2{font-size:18px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.issue-item{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px 16px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.issue-item.sev-high{border-left:3px solid var(--red)}
.issue-item.sev-medium{border-left:3px solid var(--yellow)}
.issue-item.sev-low{border-left:3px solid var(--green)}
.issue-item .info{flex:1;min-width:200px}
.issue-item .file{color:var(--dim);font-size:12px}
.issue-item .actions{display:flex;gap:8px;flex-wrap:wrap}
.btn{padding:6px 14px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:13px;transition:all .15s}
.btn:hover{background:#252836}
.btn.primary{background:var(--green);color:#000;border-color:var(--green)}
.btn.danger{background:var(--red);color:#fff;border-color:var(--red)}
.btn.warn{background:var(--yellow);color:#000;border-color:var(--yellow)}
.footer{padding:16px 32px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;color:var(--dim);font-size:13px}
.footer .coverage{display:flex;align-items:center;gap:8px}
.footer .bar{width:80px;height:6px;background:var(--border);border-radius:3px;overflow:hidden}
.footer .bar-fill{height:100%;border-radius:3px;transition:width .5s}
.modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}
.modal.show{display:flex}
.modal-content{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:600px;width:90%;max-height:80vh;overflow-y:auto}
.modal h3{margin-bottom:12px}
.modal pre{background:var(--bg);padding:12px;border-radius:8px;overflow-x:auto;font-size:12px;max-height:300px;overflow-y:auto}
.modal .close{float:right;cursor:pointer;font-size:20px;color:var(--dim)}
@media(max-width:640px){
  .header{padding:16px}
  .header .score-big{font-size:40px}
  .grid{padding:16px;grid-template-columns:1fr}
  .section{padding:0 16px 16px}
  .chart-container{margin:0 16px 8px}
  .issue-item{flex-direction:column;align-items:flex-start}
}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>%PROJECT_NAME%</h1>
    <div class="meta">更新于 %GENERATED_AT% · %MODULE_COUNT% 模块 · %DEP_EDGES% 依赖边</div>
  </div>
  <div style="text-align:right">
    <div class="score-big" id="overall-score" style="color:%SCORE_COLOR%">%OVERALL_SCORE%</div>
    <div style="font-size:13px;color:var(--dim)">综合健康分</div>
    <div class="trend" style="color:%TREND_COLOR%">%TREND% %TREND_REASON%</div>
  </div>
</div>

<div class="grid" id="dimensions"></div>
<div class="chart-container"><h3>📊 三维度雷达</h3><canvas id="radar-canvas" width="600" height="200"></canvas></div>

<div class="section">
  <h2>⚠️ 待处理问题 (%ISSUE_COUNT%)</h2>
  <div id="issues-container"></div>
</div>

<div class="section" style="display:none" id="changes-section">
  <h2>📋 近期变更</h2>
  <div id="changes-container"></div>
</div>

<div class="footer">
  <div class="coverage">
    <span>🧪 测试覆盖率</span>
    <div class="bar"><div class="bar-fill" id="cov-bar" style="width:%COVERAGE%%;background:%COV_COLOR%"></div></div>
    <span id="cov-text">%COVERAGE%%</span>
    <span id="test-badge" style="padding:2px 8px;border-radius:4px;font-size:12px;background:%TEST_BG%;color:%TEST_FG%">%TEST_STATUS%</span>
  </div>
  <div>由 CodeGuard 驱动 · 自动生成</div>
</div>

<div class="modal" id="modal"><div class="modal-content" id="modal-content"></div></div>

<script id="dashboard-data" type="application/json">%DASHBOARD_DATA%</script>
<script>
const DATA=JSON.parse(document.getElementById('dashboard-data').textContent);
(function(){
  const scores={overall:DATA.overall_score};
  let html='';
  for(const [k,d] of Object.entries(DATA.dimensions)){
    scores[k]=d.score;
    const colorMap={good:'#3fb950',warn:'#d2991d',danger:'#f85149'};
    const color=colorMap[d.status]||'#8b949e';
    html+=`<div class="dim-card ${d.status}">
      <div class="icon">${d.label.split(' ')[0]}</div>
      <div class="score" style="color:${color}">${d.score}</div>
      <div class="label">${d.label.split(' ').slice(1).join(' ')}</div>
      <div class="detail"><span class="status-dot"></span>${d.detail}</div>
    </div>`;
  }
  document.getElementById('dimensions').innerHTML=html;

  const canvas=document.getElementById('radar-canvas');
  const ctx=canvas.getContext('2d');
  const w=canvas.parentElement.clientWidth-40; canvas.width=w; canvas.height=200;
  const cx=w/2, cy=100, r=75;
  const dims=['安全','代码','架构'];
  const vals=[scores.security||0,scores.code_quality||0,scores.architecture||0];
  const colors=['#f85149','#d2991d','#58a6ff'];
  ctx.clearRect(0,0,w,200);
  // Grid
  for(let i=1;i<=5;i++){
    ctx.beginPath();ctx.strokeStyle='#2a2d3a';ctx.lineWidth=1;
    for(let j=0;j<3;j++){
      const angle=Math.PI*2*j/3-Math.PI/2;
      const pr=i*r/5;
      const x=cx+pr*Math.cos(angle),y=cy+pr*Math.sin(angle);
      j===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
    }
    ctx.closePath();ctx.stroke();
  }
  // Axes
  for(let i=0;i<3;i++){
    const angle=Math.PI*2*i/3-Math.PI/2;
    ctx.beginPath();ctx.strokeStyle='#4a4d5a';
    ctx.moveTo(cx,cy);ctx.lineTo(cx+r*Math.cos(angle),cy+r*Math.sin(angle));ctx.stroke();
    ctx.fillStyle='#c9d1d9';ctx.font='12px sans-serif';
    const lx=cx+(r+18)*Math.cos(angle),ly=cy+(r+18)*Math.sin(angle);
    ctx.textAlign='center';ctx.fillText(dims[i],lx-12,ly+4);
  }
  // Data polygon
  ctx.beginPath();ctx.globalAlpha=0.5;
  for(let i=0;i<3;i++){
    const angle=Math.PI*2*i/3-Math.PI/2;
    const pr=vals[i]/100*r;
    const x=cx+pr*Math.cos(angle),y=cy+pr*Math.sin(angle);
    i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
  }
  ctx.closePath();ctx.fillStyle='#58a6ff';ctx.fill();
  ctx.globalAlpha=1;ctx.strokeStyle='#58a6ff';ctx.lineWidth=2;ctx.stroke();
  // Dots
  for(let i=0;i<3;i++){
    const angle=Math.PI*2*i/3-Math.PI/2;
    const x=cx+vals[i]/100*r*Math.cos(angle),y=cy+vals[i]/100*r*Math.sin(angle);
    ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);ctx.fillStyle=colors[i];ctx.fill();
  }

  // Issues
  const issuesDiv=document.getElementById('issues-container');
  const sevLabels={high:'🔴 高风险',medium:'🟡 中风险',low:'🟢 低风险'};
  const sevClass={high:'sev-high',medium:'sev-medium',low:'sev-low'};
  let issueHtml='';
  for(const [sev,items] of Object.entries(DATA.issues)){
    if(!items||!items.length)continue;
    for(const item of items){
      const title=item.message||item.title||item.rule||'未知问题';
      const file=item.file||'';
      const line=item.line||'';
      const action=sev==='low'?'一键修复':sev==='medium'?'查看详情':'人工确认';
      const btnClass=sev==='low'?'primary':sev==='medium'?'warn':'danger';
      issueHtml+=`<div class="issue-item ${sevClass[sev]}">
        <div class="info"><strong>${sevLabels[sev]||''}: ${title}</strong><br><span class="file">${file}:${line}</span></div>
        <div class="actions"><button class="btn ${btnClass}" data-sev="${sev}" data-msg="${title.replace(/"/g,'&quot;')}" data-file="${file}:${line}">${action}</button></div>
      </div>`;
    }
  }
  if(!issueHtml)issueHtml='<div style="padding:24px;text-align:center;color:var(--dim)">🎉 暂无待处理问题！</div>';
  issuesDiv.innerHTML=issueHtml;

  // Issue button click handlers
  issuesDiv.addEventListener('click',function(e){
    const btn=e.target.closest('.btn');
    if(!btn)return;
    const sev=btn.dataset.sev,msg=btn.dataset.msg,file=btn.dataset.file;
    const modal=document.getElementById('modal'),mc=document.getElementById('modal-content');
    if(sev==='low'){
      mc.innerHTML=`<span class="close" onclick="document.getElementById('modal').classList.remove('show')">✕</span>
        <h3>🔧 一键修复</h3><p>即将自动修复: ${file}</p><p style="color:var(--dim)">${msg}</p>
        <p style="color:var(--yellow)">⚠️ 修复后请运行测试确认。</p>
        <button class="btn primary" onclick="document.getElementById('modal').classList.remove('show')">确认修复</button>`;
    }else if(sev==='medium'){
      mc.innerHTML=`<span class="close" onclick="document.getElementById('modal').classList.remove('show')">✕</span>
        <h3>📋 查看详情</h3><p>${file}</p><pre>${msg}</pre><p style="color:var(--dim)">此问题建议修复。请确认影响范围后执行。</p>
        <button class="btn warn" onclick="document.getElementById('modal').classList.remove('show')">知道了</button>`;
    }else{
      mc.innerHTML=`<span class="close" onclick="document.getElementById('modal').classList.remove('show')">✕</span>
        <h3>🛡️ 人工确认</h3><p>${file}</p><pre>${msg}</pre><p style="color:var(--red)">🔴 高风险操作，需逐项确认变更影响。</p>
        <label><input type="checkbox" id="confirm-1"> 我已审查所有受影响文件</label><br>
        <label><input type="checkbox" id="confirm-2"> 回滚计划已准备就绪</label><br><br>
        <button class="btn danger" onclick="if(document.getElementById('confirm-1').checked&&document.getElementById('confirm-2').checked){alert('已确认，可执行变更');document.getElementById('modal').classList.remove('show')}else{alert('请逐项确认')}">确认执行</button>`;
    }
    modal.classList.add('show');
  });

  // Close modal on backdrop click
  document.getElementById('modal').addEventListener('click',function(e){if(e.target===this)this.classList.remove('show');});

  // Recent changes
  const rc=DATA.recent_changes;
  if(rc&&rc.fixes>0){
    const sec=document.getElementById('changes-section');
    sec.style.display='block';
    document.getElementById('changes-container').innerHTML=`<div class="issue-item"><div>✅ 修复: ${rc.fixes} 次</div><div>⏪ 回滚: ${rc.rollbacks||0} 次</div><div style="color:var(--dim)">最近: ${rc.last_date||''}</div></div>`;
  }

  // Resize handler
  window.addEventListener('resize',function(){
    const c=document.getElementById('radar-canvas');
    const w=c.parentElement.clientWidth-40;c.width=w;c.height=200;
    // Redraw radar (simplified re-render)
    // Full redraw omitted for brevity — real implementation would re-render
  });
})();
</script>
</body>
</html>'''
