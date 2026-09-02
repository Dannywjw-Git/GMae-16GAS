// ===== S5 拓扑图与健康度页面 =====
// 独立模块，符合代码工程最高指南 R1（单文件≤500行）

const TopologyPage = {
  _selectedNode: null,
  _topologyData: null,
  _healthData: null,

  async render() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">系统拓扑
          <div class="page-header__actions">
            <button class="btn btn--secondary btn--sm" id="btn-topology-refresh">${Icons.refresh} 刷新</button>
          </div>
        </div>
        <div class="page-header__subtitle">GPU → 容器 → 模型 → 任务 四层资源拓扑与系统健康度</div>
      </div>
      <div id="health-score-area"><div class="loading-overlay"><div class="spinner"></div></div></div>
      <div id="topology-area"><div class="loading-overlay"><div class="spinner"></div></div></div>
      <div id="topology-detail-area"></div>
    `;
    Utils.$('#btn-topology-refresh').onclick = () => this._loadAll();
    this._loadAll();
  },

  async _loadAll() {
    try {
      const [topologyRes, healthRes] = await Promise.all([
        API.get('/api/topology'),
        API.get('/api/health/score'),
      ]);
      this._topologyData = topologyRes;
      this._healthData = healthRes;
    } catch (e) {
      console.error('Topology load error:', e);
    }
    try { this._renderHealthScore(); } catch (e) { console.error('Health render error:', e); }
    try { this._renderTopology(); } catch (e) { console.error('Topology render error:', e); }
    try { this._renderDetail(null); } catch (e) { console.error('Detail render error:', e); }
  },

  // ===== 健康度评分 =====
  _renderHealthScore() {
    const area = Utils.$('#health-score-area');
    if (!area) return;
    const data = this._healthData;
    if (!data || !data.overall_score) {
      area.innerHTML = '<div class="health-score-card health-score-card--compact"><div class="text-center py-3" style="color:var(--color-text-tertiary)">健康度数据不可用</div></div>';
      return;
    }

    const score = data.overall_score;
    const status = data.overall_status || 'good';
    const statusMap = {
      excellent: { color: '#22c55e', text: '优秀' },
      good: { color: '#0d9488', text: '良好' },
      fair: { color: '#eab308', text: '一般' },
      poor: { color: '#f97316', text: '较差' },
      critical: { color: '#ef4444', text: '危险' },
    };
    const sc = statusMap[status] || statusMap.good;
    const ringSize = 72;
    const ringR = 30;
    const circumference = 2 * Math.PI * ringR;
    const offset = circumference * (1 - score / 100);

    const dimensions = data.dimensions || [];
    const issues = data.top_issues || [];

    let dimHtml = '';
    let helperRunning = false;
    dimensions.forEach(dim => {
      const dsc = statusMap[dim.status] || statusMap.good;
      let extraHtml = '';
      if (dim.id === 'services') {
        helperRunning = !issues.some(i => i && i.indexOf('Helper') !== -1);
        if (helperRunning) {
          extraHtml = `<button class="btn btn--danger btn--sm" id="btn-stop-helper" style="margin-top:6px;width:100%;font-size:11px;padding:4px 8px">停止显存采集助手</button>`;
        } else {
          extraHtml = `<button class="btn btn--secondary btn--sm" id="btn-start-helper" style="margin-top:6px;width:100%;font-size:11px;padding:4px 8px">启动显存采集助手</button>`;
        }
      }
      dimHtml += `
        <div class="health-dimension health-dimension--compact health-dimension--${dim.status}">
          <div class="health-dimension__row">
            <span class="health-dimension__name">${dim.name}</span>
            <span class="health-dimension__score" style="color:${dsc.color}">${dim.score}</span>
          </div>
          <div class="health-dimension__desc">${dim.description || ''}</div>
          ${extraHtml}
        </div>
      `;
    });

    let issuesHtml = '';
    if (issues.length > 0) {
      issuesHtml = '<div class="health-issues health-issues--compact">';
      issues.forEach(issue => {
        issuesHtml += `<span class="health-issue-tag"><span style="color:var(--color-warning)">⚠</span> ${issue}</span>`;
      });
      issuesHtml += '</div>';
    }

    area.innerHTML = `
      <div class="health-score-card health-score-card--compact">
        <div class="health-score-compact">
          <div class="health-score-compact__left">
            <div class="health-score-ring health-score-ring--sm">
              <svg width="${ringSize}" height="${ringSize}" viewBox="0 0 ${ringSize} ${ringSize}">
                <circle class="health-score-ring__bg" cx="${ringSize/2}" cy="${ringSize/2}" r="${ringR}"/>
                <circle class="health-score-ring__fill" cx="${ringSize/2}" cy="${ringSize/2}" r="${ringR}"
                  stroke="${sc.color}"
                  stroke-dasharray="${circumference}"
                  stroke-dashoffset="${offset}"/>
              </svg>
              <div class="health-score-ring__text">
                <div class="health-score-ring__number" style="color:${sc.color};font-size:22px">${score}</div>
                <div class="health-score-ring__label" style="font-size:10px">综合评分</div>
              </div>
            </div>
            <div class="health-score-compact__info">
              <div class="health-score-status" style="color:${sc.color};font-size:16px">${sc.text}</div>
              <div class="health-score-summary" style="font-size:12px">${data.summary || '系统运行状态正常'}</div>
            </div>
          </div>
          <div class="health-score-compact__right">
            <div class="health-dimensions health-dimensions--grid">${dimHtml}</div>
          </div>
        </div>
        ${issuesHtml}
      </div>
    `;

    // 绑定显存采集助手按钮事件
    const startBtn = Utils.$('#btn-start-helper');
    const stopBtn = Utils.$('#btn-stop-helper');
    if (startBtn) startBtn.onclick = () => this._startHelper();
    if (stopBtn) stopBtn.onclick = () => this._stopHelper();
  },

  // ===== 显存采集助手（Helper）控制 =====
  async _startHelper() {
    const btn = Utils.$('#btn-start-helper');
    if (btn) { btn.disabled = true; btn.textContent = '启动中...'; }
    try {
      const res = await API.post('/api/desktop/helper/start', {});
      if (res.ok || res.running) {
        alert('显存采集助手启动成功！\n\n注意：如果弹出 UAC 管理员权限确认框，请点击"是"允许。');
        // 等待几秒后刷新
        setTimeout(() => this._loadAll(), 3000);
      } else {
        alert('显存采集助手启动失败：' + (res.msg || res.error || '未知错误'));
        if (btn) { btn.disabled = false; btn.textContent = '启动显存采集助手'; }
      }
    } catch (e) {
      alert('显存采集助手启动异常：' + e.message);
      if (btn) { btn.disabled = false; btn.textContent = '启动显存采集助手'; }
    }
  },

  async _stopHelper() {
    const btn = Utils.$('#btn-stop-helper');
    if (btn) { btn.disabled = true; btn.textContent = '停止中...'; }
    try {
      const res = await API.post('/api/desktop/helper/stop', {});
      if (res.ok) {
        alert('显存采集助手已停止');
        setTimeout(() => this._loadAll(), 2000);
      } else {
        alert('停止失败：' + (res.msg || res.error || '未知错误'));
        if (btn) { btn.disabled = false; btn.textContent = '停止显存采集助手'; }
      }
    } catch (e) {
      alert('停止异常：' + e.message);
      if (btn) { btn.disabled = false; btn.textContent = '停止显存采集助手'; }
    }
  },

  // ===== 拓扑图 =====
  _renderTopology() {
    const area = Utils.$('#topology-area');
    const data = this._topologyData;
    if (!data || !data.nodes) {
      area.innerHTML = '<div class="topology-container"><div class="text-tertiary text-center py-4">拓扑数据不可用</div></div>';
      return;
    }

    const nodes = data.nodes || [];
    const links = data.links || [];
    const stats = data.stats || {};

    // 按层分组
    const layers = [
      { id: 0, name: '物理层', label: 'GPU 硬件' },
      { id: 1, name: '容器层', label: 'Docker 容器' },
      { id: 2, name: '模型层', label: 'AI 模型' },
      { id: 3, name: '任务层', label: '运行任务' },
    ];

    // 计算布局（紧凑版）
    const nodeWidth = 120;
    const nodeHeight = 56;
    const layerGap = 80;
    const nodeGap = 16;
    const leftPadding = 90;
    const topPadding = 30;

    const layerNodes = {};
    layers.forEach(l => { layerNodes[l.id] = nodes.filter(n => n.layer === l.id); });

    // 只保留有节点的层
    const activeLayers = layers.filter(l => (layerNodes[l.id] || []).length > 0);

    // 计算每层的最大宽度
    let maxLayerWidth = 0;
    activeLayers.forEach(l => {
      const ln = layerNodes[l.id] || [];
      const w = ln.length * nodeWidth + (ln.length - 1) * nodeGap;
      if (w > maxLayerWidth) maxLayerWidth = w;
    });

    const svgWidth = Math.max(800, leftPadding + maxLayerWidth + 40);
    const svgHeight = topPadding + activeLayers.length * (nodeHeight + layerGap) + 20;

    // 计算每个节点的位置（只计算有节点的层）
    const nodePositions = {};
    activeLayers.forEach((layer, layerIdx) => {
      const ln = layerNodes[layer.id] || [];
      const totalWidth = ln.length * nodeWidth + (ln.length - 1) * nodeGap;
      const startX = leftPadding + (maxLayerWidth - totalWidth) / 2;
      const y = topPadding + layerIdx * (nodeHeight + layerGap);
      ln.forEach((node, nodeIdx) => {
        nodePositions[node.id] = {
          x: startX + nodeIdx * (nodeWidth + nodeGap),
          y: y,
          cx: startX + nodeIdx * (nodeWidth + nodeGap) + nodeWidth / 2,
          cy: y + nodeHeight / 2,
        };
      });
    });

    // 状态颜色
    const statusColors = {
      running: { fill: 'rgba(34,197,94,0.15)', stroke: 'var(--color-success)', dot: '#22c55e' },
      busy: { fill: 'rgba(234,179,8,0.15)', stroke: 'var(--color-warning)', dot: '#eab308' },
      stopped: { fill: 'rgba(107,114,128,0.15)', stroke: 'var(--color-text-tertiary)', dot: '#6b7280' },
      error: { fill: 'rgba(239,68,68,0.15)', stroke: 'var(--color-danger)', dot: '#ef4444' },
      loaded: { fill: 'rgba(139,92,246,0.15)', stroke: 'var(--color-purple)', dot: '#8b5cf6' },
      pending: { fill: 'rgba(249,115,22,0.15)', stroke: 'var(--color-orange)', dot: '#f97316' },
    };

    // 节点图标
    const typeIcons = {
      gpu: '🎮',
      container: '📦',
      model: '🧠',
      task: '⚡',
    };

    area.innerHTML = `
      <div class="topology-container">
        <div class="topology-container__header">
          <div class="topology-container__title">资源拓扑图</div>
          <div class="topology-legend">
            <div class="topology-legend__item"><div class="topology-legend__dot" style="background:#22c55e"></div>运行中</div>
            <div class="topology-legend__item"><div class="topology-legend__dot" style="background:#eab308"></div>忙碌</div>
            <div class="topology-legend__item"><div class="topology-legend__dot" style="background:#8b5cf6"></div>已加载</div>
            <div class="topology-legend__item"><div class="topology-legend__dot" style="background:#6b7280"></div>已停止</div>
          </div>
        </div>
        <div class="topology-svg-wrap">
          <svg class="topology-svg" width="${svgWidth}" height="${svgHeight}" viewBox="0 0 ${svgWidth} ${svgHeight}">
            <!-- 层级标签（只渲染有节点的层） -->
            ${activeLayers.map((layer, idx) => `
              <text class="topology-layer-label" x="16" y="${topPadding + idx * (nodeHeight + layerGap) + nodeHeight / 2 + 4}">${layer.label}</text>
            `).join('')}

            <!-- 连接线 -->
            ${links.map(link => {
              const src = nodePositions[link.source];
              const tgt = nodePositions[link.target];
              if (!src || !tgt) return '';
              // 贝塞尔曲线
              const midY = (src.cy + tgt.cy) / 2;
              const path = `M ${src.cx} ${src.cy + nodeHeight/2} C ${src.cx} ${midY}, ${tgt.cx} ${midY}, ${tgt.cx} ${tgt.cy - nodeHeight/2}`;
              return `<path class="topology-link topology-link--${link.type}" d="${path}" title="${link.description || link.type}"/>`;
            }).join('')}

            <!-- 节点 -->
            ${nodes.map(node => {
              const pos = nodePositions[node.id];
              if (!pos) return '';
              const sc = statusColors[node.status] || statusColors.stopped;
              const icon = typeIcons[node.type] || '📦';
              const isSelected = this._selectedNode === node.id ? 'topology-node--selected' : '';
              // 元信息
              let metaText = '';
              if (node.type === 'gpu') {
                metaText = `${(node.metrics?.free_mb / 1024).toFixed(1)}GB 空闲`;
              } else if (node.type === 'container') {
                metaText = node.metrics?.busy ? '忙碌中' : '空闲';
              } else if (node.type === 'model') {
                metaText = node.metrics?.size_gb ? `${node.metrics.size_gb}GB` : node.backend || '';
              } else if (node.type === 'task') {
                metaText = node.status === 'running' ? '运行中' : '等待中';
              }
              return `
                <g class="topology-node ${isSelected}" data-node-id="${node.id}" onclick="TopologyPage._selectNode('${node.id}')">
                  <rect class="topology-node__rect" x="${pos.x}" y="${pos.y}" width="${nodeWidth}" height="${nodeHeight}"
                    fill="${sc.fill}" stroke="${sc.stroke}"/>
                  <text class="topology-node__icon" x="${pos.x + 24}" y="${pos.cy}">${icon}</text>
                  <text class="topology-node__name" x="${pos.x + nodeWidth/2 + 8}" y="${pos.cy - 8}">${Utils.escapeHtml(node.name.substring(0, 16))}</text>
                  <text class="topology-node__meta" x="${pos.x + nodeWidth/2 + 8}" y="${pos.cy + 12}">${metaText}</text>
                  <circle class="topology-node__status-dot" cx="${pos.x + nodeWidth - 12}" cy="${pos.y + 12}" fill="${sc.dot}"/>
                </g>
              `;
            }).join('')}
          </svg>
        </div>
      </div>
    `;
  },

  _selectNode(nodeId) {
    this._selectedNode = nodeId;
    const node = (this._topologyData?.nodes || []).find(n => n.id === nodeId);
    this._renderTopology(); // 重新渲染以高亮选中节点
    this._renderDetail(node);
  },

  // ===== 节点详情 =====
  _renderDetail(node) {
    const area = Utils.$('#topology-detail-area');
    if (!node) {
      area.innerHTML = `
        <div class="topology-detail">
          <div class="topology-detail__empty">
            点击拓扑图中的节点查看详细信息<br>
            <span style="font-size:11px;color:var(--color-text-tertiary)">支持查看 GPU、容器、模型、任务的详细属性与连接关系</span>
          </div>
        </div>
      `;
      return;
    }

    const typeNames = { gpu: 'GPU 硬件', container: 'Docker 容器', model: 'AI 模型', task: '运行任务' };
    const statusNames = { running: '运行中', busy: '忙碌', stopped: '已停止', error: '错误', loaded: '已加载', pending: '等待中' };
    const statusColors = {
      running: 'var(--color-success)', busy: 'var(--color-warning)',
      stopped: 'var(--color-text-tertiary)', error: 'var(--color-danger)',
      loaded: 'var(--color-purple)', pending: 'var(--color-orange)',
    };
    const typeIcons = { gpu: '🎮', container: '📦', model: '🧠', task: '⚡' };

    // 查找连接
    const links = this._topologyData?.links || [];
    const nodes = this._topologyData?.nodes || [];
    const connections = links.filter(l => l.source === node.id || l.target === node.id).map(l => {
      const otherId = l.source === node.id ? l.target : l.source;
      const otherNode = nodes.find(n => n.id === otherId);
      return { ...l, otherName: otherNode?.name || otherId, direction: l.source === node.id ? '→' : '←' };
    });

    // 详细指标
    const metrics = node.metrics || {};
    const metricItems = Object.entries(metrics).filter(([k, v]) =>
      v !== null && v !== undefined && typeof v !== 'object'
    ).slice(0, 8);

    area.innerHTML = `
      <div class="topology-detail">
        <div class="topology-detail__header">
          <div class="topology-detail__icon" style="background:${statusColors[node.status] || 'var(--color-bg-3)'}20">
            ${typeIcons[node.type] || '📦'}
          </div>
          <div>
            <div class="topology-detail__title">${Utils.escapeHtml(node.name)}</div>
            <div class="topology-detail__subtitle">${typeNames[node.type] || node.type} · ${node.layer_name || 'Layer ' + node.layer}</div>
          </div>
          <span class="topology-detail__status" style="background:${statusColors[node.status] || 'var(--color-bg-3)'}20;color:${statusColors[node.status] || 'var(--color-text-secondary)'}">
            ${statusNames[node.status] || node.status}
          </span>
        </div>
        ${metricItems.length > 0 ? `
          <div class="topology-detail__grid">
            ${metricItems.map(([k, v]) => `
              <div class="topology-detail__item">
                <div class="topology-detail__label">${k}</div>
                <div class="topology-detail__value">${typeof v === 'boolean' ? (v ? '是' : '否') : Utils.escapeHtml(String(v))}</div>
              </div>
            `).join('')}
          </div>
        ` : ''}
        ${node.description ? `
          <div style="margin-top:16px;padding:10px 14px;background:var(--color-bg-1);border-radius:8px;font-size:12px;color:var(--color-text-secondary)">
            ${Utils.escapeHtml(node.description)}
          </div>
        ` : ''}
        ${connections.length > 0 ? `
          <div class="topology-detail__connections">
            <div class="topology-detail__connections-title">连接关系 (${connections.length})</div>
            ${connections.map(conn => `
              <div class="topology-detail__connection">
                <span class="topology-detail__connection-type" style="background:var(--color-bg-3);color:var(--color-text-secondary)">${conn.type}</span>
                <span style="color:var(--color-text-secondary)">${conn.direction}</span>
                <span style="font-weight:500">${Utils.escapeHtml(conn.otherName)}</span>
                <span style="margin-left:auto;font-size:11px;color:var(--color-text-tertiary)">${conn.description || ''}</span>
              </div>
            `).join('')}
          </div>
        ` : ''}
      </div>
    `;
  },
};
