const weeklyToken = () => localStorage.getItem('lift_token');
const weeklyEndpoint = '/api/weekly-leaf-report';

function el(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

async function weeklyRequest(path = '', body) {
  const response = await fetch(weeklyEndpoint + path, {
    method: body ? 'POST' : 'GET',
    headers: {'Authorization': `Bearer ${weeklyToken() || ''}`, 'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : `读取周报失败 (${response.status})`);
  }
  return data;
}

const launcher = el('button', '周叶节点分布');
launcher.type = 'button';
launcher.id = 'weekly-report-open';
launcher.hidden = true;

const dialog = el('dialog');
dialog.id = 'weekly-report';
dialog.setAttribute('aria-labelledby', 'weekly-report-title');
const head = el('header');
const title = el('h2', '周叶节点分布');
title.id = 'weekly-report-title';
const close = el('button', '关闭');
close.type = 'button';
close.addEventListener('click', () => dialog.close());
head.append(title, close);

const controls = el('section');
controls.className = 'weekly-controls';
const weekSelect = el('select');
weekSelect.setAttribute('aria-label', '选择周');
const refresh = el('button', '刷新');
refresh.type = 'button';
const freeze = el('button', '封存本周周报');
freeze.type = 'button';
freeze.className = 'weekly-freeze';
const status = el('p');
status.setAttribute('role', 'status');
const body = el('section');
body.className = 'weekly-body';
controls.append(el('label', '统计周'), weekSelect, refresh, freeze);
dialog.append(head, controls, status, body);
document.body.append(launcher, dialog);

function currentRole() {
  try { return JSON.parse(localStorage.getItem('lift_user') || 'null')?.role || null; } catch { return null; }
}

function sessionCheck() {
  let signedIn = false;
  try { signedIn = Boolean(weeklyToken()); } catch { /* corrupted session handled by login */ }
  launcher.hidden = !signedIn;
  if (!signedIn && dialog.open) dialog.close();
}
sessionCheck();
window.addEventListener('storage', sessionCheck);
setInterval(sessionCheck, 600);

function percent(value) {
  if (value === null || value === undefined) return '—';
  return `${Number(value).toFixed(2)}%`;
}

function deltaText(value) {
  if (!value) return '—';
  return `${value > 0 ? '+' : ''}${Number(value).toFixed(2)}%`;
}

function deltaClass(value) {
  if (!value) return 'flat';
  return value > 0 ? 'up' : 'down';
}

function leafConditions(leaf) {
  if (!leaf.conditions || !leaf.conditions.length) return '默认叶（无分裂条件）';
  return leaf.conditions.map(c => `${c.feature} ${c.op} ${c.value}`).join(' · ');
}

function leafTable(leaves) {
  const table = el('table');
  table.className = 'weekly-table';
  const header = table.createTHead().insertRow();
  ['叶节点路径', '分流结论', '训练样本', '训练占比', '本周台数', '本周占比', '分布'].forEach(label => {
    const th = el('th', label);
    th.scope = 'col';
    header.append(th);
  });
  const tbody = table.createTBody();
  for (const leaf of leaves) {
    const tr = tbody.insertRow();
    if (leaf.key === 'unknown') tr.className = 'unknown-row';
    const path = tr.insertCell();
    path.append(el('strong', leaf.label || leaf.key), el('small', leaf.key === 'unknown' ? '旧任务无法映射叶节点' : leafConditions(leaf)));    tr.insertCell().textContent = leaf.prediction || '—';
    tr.insertCell().textContent = leaf.training_count === null || leaf.training_count === undefined ? '—' : leaf.training_count;
    tr.insertCell().textContent = percent(leaf.training_share);
    tr.insertCell().textContent = leaf.lift_count;
    tr.insertCell().textContent = percent(leaf.share);
    const barCell = tr.insertCell();
    const bar = el('div');
    bar.className = 'weekly-bar';
    const fill = el('i');
    fill.style.width = `${Math.min(100, Number(leaf.share) || 0)}%`;
    bar.append(fill);
    barCell.append(bar);
  }
  return table;
}

function liftTable(lifts) {
  const wrap = el('div');
  wrap.className = 'weekly-lifts';
  for (const lift of lifts) {
    const details = el('details');
    const summary = el('summary');
    summary.append(
      el('strong', lift.asset_code),
      el('span', lift.building || ''),
      el('span', `叶：${lift.leaf.label}`),
      el('span', `接单 ${lift.accepted_at}`),
      lift.replaced_count ? el('span', `替下 ${lift.replaced_count} 单`) : el('span', '无替单'),
    );
    details.append(summary);
    const list = el('ol');
    for (const order of lift.orders) {
      const item = el('li');
      item.className = order.counted ? 'counted' : 'replaced';
      item.append(
        el('strong', `${order.counted ? '计入' : '已替下'} · 任务 #${order.job_id}`),
        el('p', `叶：${order.leaf.label} · 接单 ${order.accepted_at} · 完成 ${order.completed_at || '—'} · 尝试 ${order.attempt_ids.length} 次${order.retry_count ? `（重试 ${order.retry_count}）` : ''}`),
        order.replaced_by_job_id ? el('small', `被任务 #${order.replaced_by_job_id} 替下`) : el('small', '当前生效单'),
      );
      list.append(item);
    }
    details.append(list);
    wrap.append(details);
  }
  return wrap;
}

function comparisonSection(report) {
  const section = el('section');
  section.className = 'weekly-compare';
  const comparison = report.comparison;
  section.append(el('h3', '封存值对照'));
  const summaryLine = el('p', `封存于 ${comparison.frozen_at || '—'} · ${comparison.signer || ''} · 封存总台数 ${comparison.frozen_total_lifts}，当前 ${comparison.current_total_lifts}（${comparison.delta_total_lifts >= 0 ? '+' : ''}${comparison.delta_total_lifts}）`);
  summaryLine.append(el('small', comparison.distribution_changed ? '周分布已因迟回复核或新单替单发生变化' : '当前周分布与封存值一致'));
  section.append(summaryLine);
  const table = el('table');
  table.className = 'weekly-table';
  const header = table.createTHead().insertRow();
  ['叶节点', '封存台数', '封存占比', '当前台数', '当前占比', '台数差', '占比差'].forEach(label => {
    const th = el('th', label);
    th.scope = 'col';
    header.append(th);
  });
  const tbody = table.createTBody();
  for (const row of comparison.leaves) {
    const tr = tbody.insertRow();
    if (row.key === 'unknown') tr.className = 'unknown-row';
    tr.insertCell().textContent = row.label;
    tr.insertCell().textContent = row.frozen_count;
    tr.insertCell().textContent = percent(row.frozen_share);
    tr.insertCell().textContent = row.current_count;
    tr.insertCell().textContent = percent(row.current_share);
    const countCell = tr.insertCell();
    countCell.textContent = row.delta_count > 0 ? `+${row.delta_count}` : String(row.delta_count);
    countCell.className = row.delta_count ? 'changed' : '';
    const shareCell = tr.insertCell();
    shareCell.textContent = deltaText(row.delta_share);
    shareCell.className = deltaClass(row.delta_share);
  }
  section.append(table);

  if (comparison.changes.length) {
    section.append(el('h4', '逐台差异'));
    const changes = el('table');
    changes.className = 'weekly-table';
    const changeHead = changes.createTHead().insertRow();
    ['资产', '类型', '封存叶', '当前叶'].forEach(label => {
      const th = el('th', label);
      th.scope = 'col';
      changeHead.append(th);
    });
    const changeBody = changes.createTBody();
    const kindLabel = {added: '新增', removed: '移除', moved: '换叶', rerun: '同单重跑'};
    for (const change of comparison.changes) {
      const tr = changeBody.insertRow();
      tr.insertCell().textContent = change.asset_code || change.lift_id;
      tr.insertCell().textContent = kindLabel[change.kind] || change.kind;
      tr.insertCell().textContent = change.frozen_leaf_label || '—';
      tr.insertCell().textContent = change.current_leaf_label || '—';
    }
    section.append(changes);
  }
  return section;
}

function render(report) {
  weekSelect.replaceChildren(...report.weeks.map(week => {
    const option = new Option(week.label, week.start, false, week.start === report.week.start);
    return option;
  }));
  if (!report.weeks.some(week => week.start === report.week.start)) {
    weekSelect.add(new Option(report.week.label, report.week.start, true, true));
  }
  body.replaceChildren();

  const summary = el('div');
  summary.className = 'weekly-summary';
  summary.append(
    el('strong', report.week.label),
    el('span', `计入台数 ${report.total_lifts}`),
    el('span', `可映射 ${report.known_lifts}`),
    el('span', `未知 ${report.unknown.lift_count}`),
  );
  body.append(summary);

  const leafSection = el('section');
  leafSection.append(el('h3', '叶节点占比'));
  leafSection.append(el('p', '本周台数按接单时间归周，每台梯只取当周最新接单且已完成的复核；训练占比来自固定训练集。'));
  leafSection.append(leafTable([...report.leaves, report.unknown]));
  body.append(leafSection);

  if (report.comparison) body.append(comparisonSection(report));

  const liftSection = el('section');
  liftSection.append(el('h3', '逐台归叶明细'));
  liftSection.append(report.lifts.length ? liftTable(report.lifts) : el('p', '本周没有已完成的复核记录。'));
  body.append(liftSection);

  freeze.hidden = currentRole() !== 'supervisor';
  freeze.disabled = !report.can_freeze || report.total_lifts === 0;
  freeze.textContent = report.can_freeze ? '封存本周周报' : '本周已封存';
  freeze.dataset.week = report.week.start;
}

async function load(week) {
  status.textContent = '正在汇总周分布…';
  try {
    const report = await weeklyRequest(week ? `?week=${encodeURIComponent(week)}` : '');
    status.textContent = '';
    render(report);
  } catch (error) {
    status.textContent = error.message;
  }
}

weekSelect.addEventListener('change', () => load(weekSelect.value));
refresh.addEventListener('click', () => load(weekSelect.value));

freeze.addEventListener('click', async () => {
  const week = freeze.dataset.week;
  if (!week) return;
  if (!confirm('封存后本周周报将固定为对照基准，确认封存？')) return;
  freeze.disabled = true;
  status.textContent = '正在封存…';
  try {
    const result = await weeklyRequest('/snapshot', {week});
    status.textContent = `已封存 ${result.week.label}，签认人 ${result.signer}`;
    await load(week);
  } catch (error) {
    status.textContent = error.message;
    freeze.disabled = false;
  }
});

launcher.addEventListener('click', async () => {
  dialog.showModal();
  body.replaceChildren();
  await load();
});
