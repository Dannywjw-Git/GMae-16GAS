/* ============================================================
 * TopologyPage - 系统拓扑页（Ponytail 重写版）
 * 纯 HTML 分层卡片布局，删除 SVG 手动坐标计算
 * 五层：硬件 → 平台 → 容器 → 模型 → 任务
 * ============================================================ */

const TopologyPage = {
  _topologyData: null,
  _healthData: null,
  _selectedNode: null,

  _layers: [
    { id: 0, name: '宿主机硬件', icon: '🖥️', color: '#6366f1' },
    { id: 1, name: '平台软件', icon: '⚙️', color: '#8b5cf6' },
    { id: 2, name: 'AI服务容器', icon: '📦', color: '#0d9488' },
    { id: 3, name: 'AI模型', icon: '🧠', color: '#f59e0b' },
    { id: 4, name: '运行任务', icon: '⚡', color: '#ef4444' },
  ],

  _containerCategories: {
    core: { name: '核心推理', defaultExpand: true },
    gateway: { name: '前端/网关', defaultExpand: true },
    vector_db: { name: '向量数据库', defaultExpand: false },
    storage: { name: '存储/备份', defaultExpand: false },
    search: { name: '搜索', defaultExpand: false },
    monitor: { name: '监控', defaultExpand: false },
    other: { name: '其他', defaultExpand: false },
  },

  async render() {
    const container = Utils.$('#app-content');
    container.innerHTML = `
      <div class="page-header">
        <div class="page-header__title">系统拓扑
          <div class="page-header__actions">
            <button class="btn btn--secondary btn--sm" id="btn-topology-refresh">${Icons.refresh} 刷新</button>
            <button class="btn btn--ghost btn--sm" id="btn-topology-expand-all">全部展开</button>
            <button class="btn btn--ghost btn--sm" id="btn-topology-collapse-all">全部折叠</button>
          </div>
        </div>
        <div class="page-header__subtitle">硬件 → 平台 → 容器 → 模型 → 任务 五层资源拓扑</div>
      </div>
      <div id="health-score-area"><div class="loading-overlay"><div class="spinner"></div></div></div>
      <div class="topology-layout">
        <div id="topology-area" class="topology-stack"><div class="loading-overlay"><div class="spinner"></div></div></div>
        <div id="topology-detail-area" class="topology-detail-sidebar"><div class="topology-detail-placeholder">← 点击节点查看详情</div></div>
      </div>
    `;
    Utils.$('#btn-topology-refresh').onclick = () => this._loadAll();
    Utils.$('#btn-topology-expand-all').onclick = () => this._setAllDetails(true);
    Utils.$('#btn-topology-collapse-all').onclick = () => this._setAllDetails(false);
    this._loadAll();
  },

  _setAllDetails(open) {
    document.querySelectorAll('#topology-area details.topo-cat').forEach(d => { d.open = open; });
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
      Toast.error('拓扑数据加载失败');
    }
    try { this._renderHealthScore(); } catch (e) { console.error(e); }
    try { this._renderTopology(); } catch (e) { console.error(e); }
    try { this._renderDetail(null); } catch (e) { console.error(e); }
  },

  // ===== 健康度评分（保留） =====
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
    const ringSize = 72, ringR = 30;
    const circumference = 2 * Math.PI * ringR;
    const offset = circumference * (1 - score / 100);
    const dimensions = data.dimensions || [];
    const issues = data.top_issues || [];

    let dimHtml = '';
    dimensions.forEach(dim => {
      const dsc = statusMap[dim.status] || statusMap.good;
      dimHtml += `
        <div class="health-dimension health-dimension--compact health-dimension--${dim.status}">
          <div class="health-dimension__row">
            <span class="health-dimension__name">${dim.name}</span>
            <span class="health-dimension__score" style="color:${dsc.color}">${dim.score}</span>
          </div>
          <div class="health-dimension__desc">${dim.description || ''}</div>
        </div>`;
    });

    let issuesHtml = '';
    if (issues.length > 0) {
      issuesHtml = '<div class="health-issues health-issues--compact">';
      issues.forEach(issue => {
        issuesHtml += `<span class="health-issue-tag"><span style="color:var(--color-warning)">⚠</span> ${Utils.escapeHtml(issue)}</span>`;
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
                  stroke="${sc.color}" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"/>
              </svg>
              <div class="health-score-ring__text">
                <div class="health-score-ring__number" style="color:${sc.color};font-size:22px">${score}</div>
                <div class="health-score-ring__label" style="font-size:10px">综合评分</div>
              </div>
            </div>
            <div class="health-score-compact__info">
              <div class="health-score-status" style="color:${sc.color};font-size:16px">${sc.text}</div>
              <div class="health-score-summary" style="font-size:12px">${Utils.escapeHtml(data.summary || '系统运行状态正常')}</div>
            </div>
          </div>
          <div class="health-score-compact__right">
            <div class="health-dimensions health-dimensions--grid">${dimHtml}</div>
          </div>
        </div>
        ${issuesHtml}
      </div>`;
  },

  // ===== 拓扑图（纯 HTML 分层卡片） =====
  _renderTopology() {
    const area = Utils.$('#topology-area');
    const data = this._topologyData;
    if (!data || !data.nodes) {
      area.innerHTML = '<div class="text-tertiary text-center py-4">拓扑数据不可用</div>';
      return;
    }

    const nodes = data.nodes || [];
    const layerNodes = {};
    this._layers.forEach(l => { layerNodes[l.id] = nodes.filter(n => n.layer === l.id); });

    let html = '';
    this._layers.forEach((layer, idx) => {
      const ln = layerNodes[layer.id] || [];
      if (ln.length === 0) return;

      if (layer.id === 2) {
        // 容器层：按分类分组，用 <details> 原生折叠
        const byCat = {};
        ln.forEach(n => {
          const cat = n.category || n.metrics?.category || 'other';
          (byCat[cat] = byCat[cat] || []).push(n);
        });
        let catsHtml = '';
        Object.entries(byCat).forEach(([cat, catNodes]) => {
          const catInfo = this._containerCategories[cat] || this._containerCategories.other;
          const openAttr = catInfo.defaultExpand ? 'open' : '';
          catsHtml += `
            <details class="topo-cat" ${openAttr}>
              <summary>${catInfo.name} <span class="topo-cat__count">${catNodes.length}</span></summary>
              <div class="topo-nodes">${catNodes.map(n => this._nodeHtml(n)).join('')}</div>
            </details>`;
        });
        html += this._layerShell(layer, ln.length, catsHtml);
      } else {
        const nodesHtml = ln.map(n => this._nodeHtml(n)).join('');
        html += this._layerShell(layer, ln.length, `<div class="topo-nodes">${nodesHtml}</div>`);
      }

      // 层间连接箭头
      if (idx < this._layers.length - 1) {
        const nextHasNodes = (layerNodes[this._layers[idx + 1].id] || []).length > 0;
        if (nextHasNodes) {
          html += '<div class="topo-connector">↓</div>';
        }
      }
    });

    area.innerHTML = html;

    // 事件委托：节点点击
    area.onclick = (e) => {
      const nodeEl = e.target.closest('.topo-node');
      if (nodeEl) {
        const nodeId = nodeEl.dataset.nodeId;
        this._selectNode(nodeId);
      }
    };
  },

  _layerShell(layer, count, content) {
    return `
      <section class="topo-layer" style="--layer-color:${layer.color}">
        <h3 class="topo-layer__title">${layer.icon} ${layer.name} <span class="topo-layer__count">${count}</span></h3>
        ${content}
      </section>`;
  },

  _nodeHtml(n) {
    const isSelected = this._selectedNode === n.id;
    const icon = this._getTypeIcon(n.type);
    const desc = (n.description || '').replace(/None/g, '—').replace(/null/g, '—');
    return `
      <div class="topo-node topo-node--${n.status || 'unknown'} ${isSelected ? 'topo-node--selected' : ''}" data-node-id="${Utils.escapeHtml(n.id)}">
        <span class="topo-node__icon">${icon}</span>
        <div class="topo-node__body">
          <div class="topo-node__name" title="${Utils.escapeHtml(n.name)}">${Utils.escapeHtml(n.name)}</div>
          <div class="topo-node__desc" title="${Utils.escapeHtml(desc)}">${Utils.escapeHtml(desc)}</div>
        </div>
        <span class="topo-node__status"></span>
      </div>`;
  },

  _getTypeIcon(type) {
    const map = {
      cpu: '⚡', memory: '💾', gpu: '🎮', disk: '💿', network: '🌐',
      os: '🪟', wsl: '🐧', docker: '🐳', python: '🐍',
      container: '📦', model: '🧠', task: '⚡',
    };
    return map[type] || '📦';
  },

  _selectNode(nodeId) {
    this._selectedNode = this._selectedNode === nodeId ? null : nodeId;
    // 只更新选中样式，不重渲染拓扑（保留 details 折叠状态）
    document.querySelectorAll('.topo-node').forEach(el => {
      el.classList.toggle('topo-node--selected', el.dataset.nodeId === this._selectedNode);
    });
    this._renderDetail(this._selectedNode);
  },

  _statusText(status) {
    const map = { running: '运行中', idle: '未加载', busy: '忙碌', error: '错误', stopped: '已停止', pending: '等待中', loading: '加载中' };
    return map[status] || status || '未知';
  },

  _renderDetail(nodeId) {
    const area = Utils.$('#topology-detail-area');
    if (!area) return;
    if (!nodeId) {
      area.innerHTML = '<div class="topology-detail-placeholder">← 点击节点查看详情</div>';
      return;
    }
    const node = (this._topologyData?.nodes || []).find(n => n.id === nodeId);
    if (!node) {
      area.innerHTML = '<div class="topology-detail-placeholder">节点数据不可用</div>';
      return;
    }
    const metrics = node.metrics || {};
    const metricRows = Object.entries(metrics)
      .filter(([k, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => `<tr><td style="width:140px;font-weight:600;color:var(--color-text-secondary)">${Utils.escapeHtml(k)}</td><td>${Utils.escapeHtml(String(v))}</td></tr>`)
      .join('');

    area.innerHTML = `
      <div class="card mt-4">
        <div class="card__header">
          <div class="card__title">${this._getTypeIcon(node.type)} ${Utils.escapeHtml(node.name)}</div>
          <span class="badge badge--${node.status === 'running' ? 'success' : node.status === 'busy' ? 'warning' : node.status === 'error' ? 'danger' : 'neutral'}">${this._statusText(node.status)}</span>
        </div>
        <div class="card__body">
          <div class="text-tertiary mb-3" style="font-size:12px">${Utils.escapeHtml(node.description || '')}</div>
          ${metricRows ? `<table class="table"><tbody>${metricRows}</tbody></table>` : '<div class="text-tertiary">无详细指标</div>'}
        </div>
      </div>`;
  },
};
