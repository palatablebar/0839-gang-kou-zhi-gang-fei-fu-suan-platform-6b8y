(function () {
  var $ = function (id) { return document.getElementById(id); };
  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
  async function request(url, options) {
    var response = await fetch(url, Object.assign({ headers: { 'Content-Type': 'application/json' } }, options || {}));
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
    return data;
  }
  function notice(text) {
    var node = $('notice');
    if (node) node.textContent = text || '';
  }
  function formData() {
    return {
      container_id: $('ac-container').value.trim(),
      gate_in: $('ac-gate-in').value,
      free_days: $('ac-free-days').value,
      period: $('ac-period').value.trim(),
      gate_out: $('ac-gate-out').value || undefined
    };
  }
  function renderEntries(entries) {
    var body = $('ac-body');
    if (!entries || !entries.length) {
      body.innerHTML = '<tr><td class="empty" colspan="6">暂无分录</td></tr>';
      return;
    }
    body.innerHTML = entries.map(function (row) {
      return '<tr><td>' + esc(row.period) + '</td><td>' + esc(row.container_id) + '</td>' +
        '<td><code>' + esc(row.entry_type) + '</code></td>' +
        '<td class="num">' + esc(row.amount_cents) + '</td>' +
        '<td class="num">' + esc(row.cumulative_cents) + '</td>' +
        '<td class="num">' + esc(row.charge_days) + '</td></tr>';
    }).join('');
  }
  async function refresh(containerId) {
    var query = containerId ? ('?container_id=' + encodeURIComponent(containerId)) : '';
    renderEntries(await request('/api/accruals/entries' + query));
  }
  async function call(url, payload, keepResult) {
    try {
      notice('');
      var data = await request(url, { method: 'POST', body: JSON.stringify(payload) });
      if (keepResult) {
        $('ac-result').innerHTML =
          '<div class="ledger-row"><span>历月入账合计(分)</span><strong>' + esc(data.booked_cents) + '</strong></div>' +
          '<div class="ledger-row"><span>整趟实费(分)</span><strong>' + esc(data.actual_cents) + '</strong></div>' +
          '<div class="ledger-row"><span>差额(分)</span><strong>' + esc(data.difference_cents) + '</strong></div>' +
          '<div class="ledger-row"><span>对账结论</span><strong class="' +
          (data.balanced ? 'check-ok' : 'check-bad') + '">' + (data.balanced ? '平衡' : '不平') + '</strong></div>';
      } else {
        notice('已' + (data.created === false ? '幂等返回（未重复入账）' : '入账') + '：' + data.entry_type + ' ' + data.period);
      }
      if (payload.container_id) refresh(payload.container_id);
    } catch (error) { notice(error.message); }
  }
  function boot() {
    if (!$('panel-accrual')) return;
    $('ac-accrue').addEventListener('click', function () {
      call('/api/accruals/entries', formData());
    });
    $('ac-settle').addEventListener('click', function () {
      call('/api/accruals/settlements', formData());
    });
    $('ac-close').addEventListener('click', function () {
      var period = $('ac-period').value.trim();
      if (!period) { notice('请先填写历月 YYYY-MM'); return; }
      call('/api/accruals/periods/' + encodeURIComponent(period) + '/close', {});
    });
    $('ac-reconcile').addEventListener('click', function () {
      call('/api/accruals/reconcile', formData(), true);
    });
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
