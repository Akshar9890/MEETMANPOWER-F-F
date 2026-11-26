(() => {
  const state = {
    view: 'dashboard',
    boot: null,
    activeBatch: null,
    activeFnf: null,
    activeRevision: null,
    settingsTab: 'company',
  };

  const esc = (v) =>
    String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const inr = (n) => '₹' + Number(n || 0).toLocaleString('en-IN');

  function toast(msg, isErr = false) {
    const el = document.getElementById('toast-box');
    el.textContent = msg;
    el.className = 'toast' + (isErr ? ' err' : '');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.add('hidden'), 4500);
  }

  async function api(method, params = {}, isPost = false) {
    const url = `/api/method/kesari_jefs.api.${method}`;
    let resp;
    if (isPost) {
      const form = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        form.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v ?? ''));
      }
      resp = await fetch(url, {
        method: 'POST',
        headers: { 'X-Frappe-CSRF-Token': window.JEFS_CSRF, 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form.toString(),
      });
    } else {
      const qs = new URLSearchParams(params).toString();
      resp = await fetch(qs ? `${url}?${qs}` : url);
    }
    const json = await resp.json();
    if (!resp.ok || json.exc) {
      let msg = json._server_messages ? JSON.parse(JSON.parse(json._server_messages)[0]).message : json.exception || 'Request failed';
      throw new Error(msg.replace(/<[^>]+>/g, ''));
    }
    return json.message;
  }

  async function apiUpload(method, formData) {
    const resp = await fetch(`/api/method/kesari_jefs.api.${method}`, {
      method: 'POST',
      headers: { 'X-Frappe-CSRF-Token': window.JEFS_CSRF },
      body: formData,
    });
    const json = await resp.json();
    if (!resp.ok || json.exc) {
      let msg = json._server_messages ? JSON.parse(JSON.parse(json._server_messages)[0]).message : json.exception || 'Upload failed';
      throw new Error(msg.replace(/<[^>]+>/g, ''));
    }
    return json.message;
  }

  function openModal(title, html) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = html;
    document.getElementById('modal-backdrop').classList.remove('hidden');
  }

  function closeModal() {
    document.getElementById('modal-backdrop').classList.add('hidden');
  }

  document.getElementById('modal-close').onclick = closeModal;
  document.getElementById('modal-backdrop').onclick = (e) => {
    if (e.target.id === 'modal-backdrop') closeModal();
  };

  function setHeader(title, sub = '', actionsHtml = '') {
    document.getElementById('view-title').textContent = title;
    document.getElementById('view-subtitle').textContent = sub;
    document.getElementById('topbar-actions').innerHTML = actionsHtml;
  }

  async function loadView(view) {
    state.view = view;
    document.querySelectorAll('#sidebar-nav .nav-item').forEach((b) => {
      b.classList.toggle('active', b.dataset.view === view);
    });
    try {
      state.boot = await api('get_bootstrap');
      document.getElementById('user-chip').textContent = `${state.boot.user} (${state.boot.roles.filter((r) => r.startsWith('JEFS')).join(', ') || 'Admin'})`;
      const handlers = {
        dashboard: renderDashboard,
        uploads: renderUploads,
        employees: renderEmployees,
        'joining-kit': renderJoiningKit,
        fnf: renderFnF,
        certificates: renderCertificates,
        'wage-revision': renderWageRevision,
        documents: renderDocuments,
        reports: renderReports,
        settings: renderSettings,
      };
      await handlers[view]();
    } catch (err) {
      toast(err.message, true);
    }
  }

  document.querySelectorAll('#sidebar-nav .nav-item').forEach((btn) => {
    btn.onclick = () => loadView(btn.dataset.view);
  });

  // 1. DASHBOARD
  async function renderDashboard() {
    const s = state.boot.stats;
    const co = state.boot.company;
    setHeader('Dashboard', `${co.legal_name} · Ref Prefix: ${co.ref_prefix}`, `
      <button class="btn btn-primary" onclick="window._jefsNav('uploads')">+ Upload Excel</button>
      <button class="btn" onclick="window._jefsNav('joining-kit')">Joining Kit</button>
      <button class="btn" onclick="window._jefsNav('fnf')">Exits &amp; F&amp;F</button>
    `);
    const overdueHtml = s.overdue_fnf > 0
      ? `<div class="banner banner-err"><b>Attention:</b> ${s.overdue_fnf} exit(s) have exceeded the Code on Wages 2-working-day F&amp;F payment deadline!</div>`
      : '';

    const feedRows = ['EMPLOYEE', 'SALARY', 'BONUS', 'LEAVE'].map((f) => {
      const b = state.boot.last_uploads[f];
      return `<tr>
        <td><b>${f}</b></td>
        <td>${b ? esc(b.file_name) : '<span class="muted">Not uploaded yet</span>'}</td>
        <td>${b ? b.ok_rows : '-'}</td>
        <td>${b ? esc(b.uploaded_by) : '-'}</td>
        <td>${b ? esc(String(b.committed_at).slice(0, 16)) : '-'}</td>
      </tr>`;
    }).join('');

    const siteRows = (state.boot.site_rules || []).map((r) => `
      <tr>
        <td><b>${esc(r.site_code)}</b></td>
        <td>${esc(r.site_name)}</td>
        <td>${r.include_bonus ? '<span class="pill pill-ok">Yes</span>' : '<span class="pill pill-neutral">No</span>'}</td>
        <td>${r.include_leave ? '<span class="pill pill-ok">Yes</span>' : '<span class="pill pill-neutral">No</span>'}</td>
        <td>${r.include_gratuity ? '<span class="pill pill-ok">Yes</span>' : '<span class="pill pill-neutral">No</span>'}</td>
      </tr>`).join('');

    document.getElementById('view-content').innerHTML = `
      ${overdueHtml}
      <div class="grid-4">
        <div class="card"><div class="muted">Active Employees</div><div class="stat-val">${s.active_employees}</div><div class="muted">Joiners this month: ${s.joiners_this_month}</div></div>
        <div class="card"><div class="muted">Exits Pending F&amp;F</div><div class="stat-val">${s.pending_fnf}</div><div class="muted">Overdue (&gt;2 working days): <b style="color:${s.overdue_fnf ? '#dc2626' : '#16a34a'}">${s.overdue_fnf}</b></div></div>
        <div class="card"><div class="muted">F&amp;F Awaiting Approval</div><div class="stat-val">${s.awaiting_approval}</div><div class="muted">Maker-checker queue</div></div>
        <div class="card"><div class="muted">Documents Generated</div><div class="stat-val">${s.docs_generated}</div><div class="muted">Missing data rows: ${s.missing_data_count}</div></div>
      </div>
      <div class="grid-2">
        <div class="card">
          <h3>Last Committed Excel Feeds</h3>
          <div class="table-wrap"><table><thead><tr><th>Feed</th><th>File</th><th>Valid Rows</th><th>By</th><th>At</th></tr></thead><tbody>${feedRows}</tbody></table></div>
        </div>
        <div class="card">
          <h3>Client Site F&amp;F Rules</h3>
          <div class="table-wrap"><table><thead><tr><th>Site</th><th>Principal Employer</th><th>Bonus</th><th>Leave</th><th>Gratuity</th></tr></thead><tbody>${siteRows}</tbody></table></div>
        </div>
      </div>
    `;
  }

  // 2. UPLOADS
  async function renderUploads() {
    setHeader('Excel Uploads & Photo ZIP', '4 Master Feeds (.xlsx / .xls / .csv) with saved column mapping & validation');
    const batches = await api('list_upload_batches');

    const tiles = [
      { id: 'EMPLOYEE', title: '1. Employee Excel', desc: 'Personal details, Aadhaar/PAN, bank, DOJ, exit & nominees', extra: '' },
      { id: 'SALARY', title: '2. Salary Excel', desc: 'Monthly Basic, DA, HRA, Gross, PF, ESI, PT, Paid days', extra: '<label>Period (YYYY-MM)</label><input type="text" id="sal-period" value="2027-01" />' },
      { id: 'BONUS', title: '3. Bonus Report', desc: 'FY working days, bonus wage, bonus already paid', extra: '<label>Financial Year</label><input type="text" id="bon-fy" value="2026-27" />' },
      { id: 'LEAVE', title: '4. Leave Report', desc: 'Accrued EL balances & leaves taken for F&F encashment', extra: '' },
    ];

    const tileHtml = tiles.map((t) => `
      <div class="card">
        <h3>${t.title}</h3>
        <p class="muted">${t.desc}</p>
        ${t.extra}
        <div style="margin:8px 0;"><input type="file" id="file-${t.id}" accept=".xlsx,.xls,.csv" /></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="window._uploadFeed('${t.id}')">Upload &amp; Validate</button>
          <a class="btn btn-sm" href="/api/method/kesari_jefs.api.download_sample_template?feed=${t.id}">Sample .xlsx</a>
        </div>
      </div>`).join('');

    let wizardHtml = '';
    if (state.activeBatch) {
      const b = state.activeBatch;
      const mapRows = b.headers.map((h) => `
        <tr>
          <td><b>${esc(h)}</b></td>
          <td>
            <select class="col-map-sel" data-col="${esc(h)}">
              <option value="">-- Ignore --</option>
              ${b.system_fields.map((sf) => `<option value="${sf}" ${b.mapping[h] === sf ? 'selected' : ''}>${sf}</option>`).join('')}
            </select>
          </td>
        </tr>`).join('');
      const errRows = (b.preview_errors || []).map((e) => `<tr><td>${e.row_num}</td><td style="color:#991b1b">${esc(e.errors)}</td><td class="mono">${esc(JSON.stringify(e.raw).slice(0, 140))}</td></tr>`).join('');
      const okRows = (b.preview_valid || []).slice(0, 10).map((r) => `<tr><td>${r.__row_num}</td><td><b>${esc(r.employee_code)}</b></td><td class="mono">${esc(JSON.stringify(r).slice(0, 140))}</td></tr>`).join('');

      wizardHtml = `
        <div class="card" style="border-color:#2563eb;">
          <h3>Batch Preview: ${esc(b.batch_id)} (${esc(b.feed)} · ${esc(b.file_name)})</h3>
          <div style="display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap;">
            <span class="pill pill-neutral">Total: ${b.total_rows}</span>
            <span class="pill pill-ok">Valid: ${b.ok_rows}</span>
            <span class="pill ${b.error_rows ? 'pill-err' : 'pill-ok'}">Errors: ${b.error_rows}</span>
            ${b.missing_required.length ? `<span class="pill pill-err">Missing Required Map: ${esc(b.missing_required.join(', '))}</span>` : ''}
          </div>
          <details style="margin-bottom:12px;">
            <summary style="cursor:pointer;font-weight:600;">Step 2: Column Mapping (auto-saved per feed)</summary>
            <div class="table-wrap" style="margin-top:8px;"><table><thead><tr><th>Excel Header</th><th>System Field</th></tr></thead><tbody>${mapRows}</tbody></table></div>
            <button class="btn btn-sm" style="margin-top:8px;" onclick="window._applyMapping('${b.batch_id}')">Apply &amp; Re-validate</button>
          </details>
          ${errRows ? `<h4>Validation Errors</h4><div class="table-wrap" style="max-height:220px;overflow:auto;"><table><thead><tr><th>Row</th><th>Error</th><th>Data</th></tr></thead><tbody>${errRows}</tbody></table></div>` : ''}
          ${okRows ? `<h4 style="margin-top:10px;">Valid Preview (first 10)</h4><div class="table-wrap" style="max-height:220px;overflow:auto;"><table><thead><tr><th>Row</th><th>Emp Code</th><th>Mapped Values</th></tr></thead><tbody>${okRows}</tbody></table></div>` : ''}
          <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">
            <button class="btn btn-success" onclick="window._commitBatch('${b.batch_id}')" ${b.ok_rows === 0 || b.missing_required.length ? 'disabled' : ''}>Commit ${b.ok_rows} Valid Row(s)</button>
            ${b.error_rows ? `<a class="btn" href="/api/method/kesari_jefs.api.download_batch_errors?batch_id=${encodeURIComponent(b.batch_id)}">Download Error Report (.xlsx)</a>` : ''}
            <button class="btn btn-danger" onclick="window._discardBatch('${b.batch_id}')">Discard</button>
          </div>
        </div>`;
    }

    const batchRows = batches.map((b) => `
      <tr>
        <td class="mono">${esc(b.name)}</td>
        <td><b>${esc(b.feed)}</b></td>
        <td>${esc(b.file_name)}</td>
        <td>${b.ok_rows}/${b.total_rows} (${b.error_rows} err)</td>
        <td><span class="pill ${b.status === 'COMMITTED' ? 'pill-ok' : b.status === 'DISCARDED' ? 'pill-err' : 'pill-warn'}">${esc(b.status)}</span></td>
        <td>${esc(b.uploaded_by)}</td>
      </tr>`).join('');

    document.getElementById('view-content').innerHTML = `
      <div class="grid-4">${tileHtml}</div>
      ${wizardHtml}
      <div class="card">
        <h3>Employee Photos ZIP Upload (<code>&lt;emp_code&gt;.jpg / .png</code>)</h3>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
          <input type="file" id="photo-zip" accept=".zip" style="max-width:340px;" />
          <button class="btn btn-primary btn-sm" onclick="window._uploadPhotos()">Upload Photos ZIP</button>
        </div>
      </div>
      <div class="card">
        <h3>Upload History</h3>
        <div class="table-wrap"><table><thead><tr><th>Batch</th><th>Feed</th><th>File</th><th>Rows</th><th>Status</th><th>Uploaded By</th></tr></thead><tbody>${batchRows}</tbody></table></div>
      </div>
    `;
  }

  window._uploadFeed = async (feed) => {
    const inp = document.getElementById(`file-${feed}`);
    if (!inp.files.length) return toast('Choose a file first', true);
    const fd = new FormData();
    fd.append('feed', feed);
    fd.append('file', inp.files[0]);
    if (feed === 'SALARY') fd.append('period', document.getElementById('sal-period').value);
    if (feed === 'BONUS') fd.append('fy', document.getElementById('bon-fy').value);
    try {
      state.activeBatch = await apiUpload('upload_feed_file', fd);
      toast(`Validated ${state.activeBatch.total_rows} rows`);
      renderUploads();
    } catch (e) { toast(e.message, true); }
  };

  window._applyMapping = async (batchId) => {
    const map = {};
    document.querySelectorAll('.col-map-sel').forEach((s) => { map[s.dataset.col] = s.value; });
    try {
      const updated = await api('update_batch_mapping', { batch_id: batchId, mapping_json: map }, true);
      state.activeBatch = { ...state.activeBatch, ...updated };
      toast('Mapping saved & re-validated');
      renderUploads();
    } catch (e) { toast(e.message, true); }
  };

  window._commitBatch = async (batchId) => {
    try {
      const res = await api('commit_batch', { batch_id: batchId }, true);
      toast(`Committed: ${res.inserted} inserted, ${res.updated} updated`);
      state.activeBatch = null;
      renderUploads();
    } catch (e) { toast(e.message, true); }
  };

  window._discardBatch = async (batchId) => {
    try {
      await api('discard_batch', { batch_id: batchId }, true);
      state.activeBatch = null;
      toast('Batch discarded');
      renderUploads();
    } catch (e) { toast(e.message, true); }
  };

  window._uploadPhotos = async () => {
    const inp = document.getElementById('photo-zip');
    if (!inp.files.length) return toast('Select a ZIP file', true);
    const fd = new FormData();
    fd.append('file', inp.files[0]);
    try {
      const res = await apiUpload('upload_photos_zip', fd);
      toast(`Matched ${res.matched.length} photo(s); ${res.unmatched.length} unmatched`);
    } catch (e) { toast(e.message, true); }
  };

  // 3. EMPLOYEES
  async function renderEmployees() {
    setHeader('Employees', 'Master directory with masked Aadhaar/PAN/bank, nominees & history');
    const q = document.getElementById('emp-q')?.value || '';
    const status = document.getElementById('emp-status')?.value || '';
    const emps = await api('list_employees', { q, status });

    const rows = emps.map((e) => `
      <tr>
        <td><b>${esc(e.employee_code)}</b></td>
        <td>${esc(e.full_name)}</td>
        <td>${esc(e.designation)}</td>
        <td>${esc(e.client_site)}</td>
        <td>${esc(e.date_of_joining)}</td>
        <td class="mono">${esc(e.aadhaar_masked || '-')}</td>
        <td><span class="pill ${e.kit_ready ? 'pill-ok' : 'pill-warn'}">${e.kit_ready ? 'Kit Ready' : 'Missing Fields'}</span></td>
        <td><span class="pill ${e.status === 'ACTIVE' ? 'pill-ok' : 'pill-neutral'}">${esc(e.status)}</span></td>
        <td>
          <button class="btn btn-sm" onclick="window._openEmp('${esc(e.employee_code)}')">View</button>
          ${e.status === 'ACTIVE' ? `<button class="btn btn-sm btn-danger" onclick="window._openExitModal('${esc(e.employee_code)}')">Exit</button>` : ''}
        </td>
      </tr>`).join('');

    document.getElementById('view-content').innerHTML = `
      <div class="card">
        <div class="form-row">
          <div><label>Search</label><input type="text" id="emp-q" value="${esc(q)}" placeholder="Code, name, site..." /></div>
          <div><label>Status</label><select id="emp-status"><option value="">All</option><option value="ACTIVE" ${status==='ACTIVE'?'selected':''}>Active</option><option value="EXITED" ${status==='EXITED'?'selected':''}>Exited</option></select></div>
          <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" onclick="window._reloadEmps()">Filter</button></div>
        </div>
        <div class="table-wrap"><table><thead><tr><th>Code</th><th>Name</th><th>Designation</th><th>Site</th><th>DOJ</th><th>Aadhaar</th><th>Kit</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows || '<tr><td colspan="9" class="muted">No employees yet. Upload Employee Excel first.</td></tr>'}</tbody></table></div>
      </div>`;
  }
  window._reloadEmps = () => renderEmployees();

  window._openEmp = async (code) => {
    try {
      const d = await api('get_employee_detail', { employee_code: code });
      const e = d.employee;
      const nomRows = d.nominees.map((n, idx) => `
        <tr>
          <td><select class="n-purpose"><option ${n.purpose==='GRATUITY'?'selected':''}>GRATUITY</option><option ${n.purpose==='PF'?'selected':''}>PF</option><option ${n.purpose==='EPS'?'selected':''}>EPS</option></select></td>
          <td><input type="text" class="n-name" value="${esc(n.nominee_name)}" /></td>
          <td><input type="text" class="n-rel" value="${esc(n.relationship)}" /></td>
          <td><input type="date" class="n-dob" value="${esc(n.dob)}" /></td>
          <td><input type="number" class="n-share" value="${esc(n.share_pct)}" /></td>
        </tr>`).join('');

      openModal(`${e.full_name} (${e.employee_code})`, `
        <div class="form-row">
          <div><b>Father/Husband:</b> ${esc(e.father_or_husband_name || '-')}</div>
          <div><b>DOB:</b> ${esc(e.dob || '-')}</div>
          <div><b>Mobile:</b> ${esc(e.mobile || '-')}</div>
          <div><b>Site:</b> ${esc(e.client_site || '-')}</div>
          <div><b>Aadhaar:</b> <span class="mono" id="pii-aad">${esc(e.aadhaar_masked || '-')}</span></div>
          <div><b>PAN:</b> <span class="mono" id="pii-pan">${esc(e.pan_masked || '-')}</span></div>
          <div><b>Bank:</b> <span class="mono" id="pii-bank">${esc(e.bank_account_masked || '-')}</span> (${esc(e.ifsc || '-')})</div>
          <div><b>Photo:</b> ${e.has_photo ? '<span class="pill pill-ok">Uploaded</span>' : '<span class="pill pill-err">Missing</span>'}</div>
        </div>
        <button class="btn btn-sm" onclick="window._revealPii('${esc(e.employee_code)}')">Reveal Full PII (Audited)</button>
        <hr/>
        <h4>Nominees (Total per purpose must equal 100%)</h4>
        <table><thead><tr><th>Purpose</th><th>Name</th><th>Relation</th><th>DOB</th><th>Share %</th></tr></thead><tbody id="nom-tbody">${nomRows}</tbody></table>
        <div style="margin-top:8px;display:flex;gap:8px;">
          <button class="btn btn-sm" onclick="window._addNomRow()">+ Add Nominee</button>
          <button class="btn btn-sm btn-primary" onclick="window._saveNominees('${esc(e.employee_code)}')">Save Nominees</button>
        </div>
        <hr/>
        <h4>Salary History (${d.salaries.length}) · Documents (${d.documents.length})</h4>
        <div class="muted">${d.salaries.map((s) => `${s.period}: Gross ${inr(Math.round(s.gross_paise/100))}`).join(' | ') || 'No salary uploaded'}</div>
      `);
    } catch (err) { toast(err.message, true); }
  };

  window._revealPii = async (code) => {
    try {
      const r = await api('reveal_employee_pii', { employee_code: code }, true);
      document.getElementById('pii-aad').textContent = r.aadhaar || '-';
      document.getElementById('pii-pan').textContent = r.pan || '-';
      document.getElementById('pii-bank').textContent = r.bank_account || '-';
      toast('PII reveal logged in Audit Log');
    } catch (e) { toast(e.message, true); }
  };

  window._addNomRow = () => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><select class="n-purpose"><option>GRATUITY</option><option>PF</option><option>EPS</option></select></td><td><input type="text" class="n-name" /></td><td><input type="text" class="n-rel" /></td><td><input type="date" class="n-dob" /></td><td><input type="number" class="n-share" value="100" /></td>`;
    document.getElementById('nom-tbody').appendChild(tr);
  };

  window._saveNominees = async (code) => {
    const rows = [];
    document.querySelectorAll('#nom-tbody tr').forEach((tr) => {
      const name = tr.querySelector('.n-name').value.trim();
      if (!name) return;
      rows.push({
        purpose: tr.querySelector('.n-purpose').value,
        nominee_name: name,
        relationship: tr.querySelector('.n-rel').value,
        dob: tr.querySelector('.n-dob').value,
        share_pct: Number(tr.querySelector('.n-share').value || 0),
      });
    });
    try {
      await api('save_nominees', { employee_code: code, nominees_json: rows }, true);
      toast('Nominees saved');
      closeModal();
      renderEmployees();
    } catch (e) { toast(e.message, true); }
  };

  window._openExitModal = (code) => {
    openModal(`Record Exit — ${code}`, `
      <div class="form-row">
        <div><label>Exit Date</label><input type="date" id="ex-date" value="2027-01-15" /></div>
        <div><label>Last Working Day</label><input type="date" id="ex-lwd" value="2027-01-15" /></div>
        <div><label>Reason</label><select id="ex-reason"><option>RESIGNATION</option><option>RETIREMENT</option><option>END_OF_CONTRACT</option><option>TERMINATION</option><option>ABSCONDING</option><option>DEATH</option></select></div>
        <div><label>Conduct</label><input type="text" id="ex-conduct" value="Good" /></div>
      </div>
      <button class="btn btn-primary" onclick="window._submitExit('${esc(code)}')">Record Exit &amp; Initiate F&amp;F</button>
    `);
  };

  window._submitExit = async (code) => {
    try {
      const res = await api('record_employee_exit', {
        employee_code: code,
        exit_date: document.getElementById('ex-date').value,
        last_working_day: document.getElementById('ex-lwd').value,
        exit_reason: document.getElementById('ex-reason').value,
        conduct: document.getElementById('ex-conduct').value,
      }, true);
      closeModal();
      state.activeFnf = res;
      toast('Exit recorded & F&F draft created');
      loadView('fnf');
    } catch (e) { toast(e.message, true); }
  };

  // 4. JOINING KIT & POLICE
  async function renderJoiningKit() {
    setHeader('Joining Kit & Police Verification', 'Readiness matrix, batch PDF/DOCX generation & CR-80 ID card print sheet');
    const emps = await api('list_employees', {});
    const badge = (info) => info.ready
      ? '<span class="pill pill-ok">✓</span>'
      : `<span class="pill pill-err" title="${esc(info.missing.join(', '))}">✗ ${esc(info.missing[0])}</span>`;

    const rows = emps.map((e) => `
      <tr>
        <td><input type="checkbox" class="kit-chk" value="${esc(e.employee_code)}" checked /></td>
        <td><b>${esc(e.employee_code)}</b><br/><span class="muted">${esc(e.full_name)}</span></td>
        <td>${badge(e.readiness.OFFER_LETTER)}</td>
        <td>${badge(e.readiness.APPOINTMENT_LETTER)}</td>
        <td>${badge(e.readiness.GRATUITY_FORM_F)}</td>
        <td>${badge(e.readiness.ID_CARD)}</td>
        <td>${badge(e.readiness.EPFO_FORM_2)}</td>
        <td>${badge(e.readiness.POLICE_VERIFICATION)}</td>
      </tr>`).join('');

    document.getElementById('view-content').innerHTML = `
      <div class="card">
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;align-items:center;">
          <label style="display:inline-flex;gap:4px;align-items:center;"><input type="checkbox" class="doc-chk" value="OFFER_LETTER" checked /> Offer</label>
          <label style="display:inline-flex;gap:4px;align-items:center;"><input type="checkbox" class="doc-chk" value="APPOINTMENT_LETTER" checked /> Appointment</label>
          <label style="display:inline-flex;gap:4px;align-items:center;"><input type="checkbox" class="doc-chk" value="GRATUITY_FORM_F" checked /> Form IV / F</label>
          <label style="display:inline-flex;gap:4px;align-items:center;"><input type="checkbox" class="doc-chk" value="ID_CARD" checked /> ID Card</label>
          <label style="display:inline-flex;gap:4px;align-items:center;"><input type="checkbox" class="doc-chk" value="EPFO_FORM_2" checked /> EPFO Form 11</label>
          <label style="display:inline-flex;gap:4px;align-items:center;"><input type="checkbox" class="doc-chk" value="POLICE_VERIFICATION" checked /> Police Letter</label>
          <button class="btn btn-primary" onclick="window._generateKit()">Generate Selected &amp; Download ZIP</button>
          <button class="btn" onclick="window._generateIdSheet()">ID Card A4 Print Sheet</button>
        </div>
        <div id="kit-result"></div>
        <div class="table-wrap"><table><thead><tr><th>Sel</th><th>Employee</th><th>Offer</th><th>Appt</th><th>Gratuity</th><th>ID Card</th><th>EPFO</th><th>Police</th></tr></thead><tbody>${rows}</tbody></table></div>
      </div>`;
  }

  window._generateKit = async () => {
    const codes = Array.from(document.querySelectorAll('.kit-chk:checked')).map((c) => c.value);
    const docs = Array.from(document.querySelectorAll('.doc-chk:checked')).map((c) => c.value);
    if (!codes.length || !docs.length) return toast('Select employees and documents', true);
    try {
      toast('Generating PDFs via Gotenberg...');
      const res = await api('generate_documents', { employee_codes_json: codes, doc_types_json: docs, merge_kit: 1 }, true);
      const box = document.getElementById('kit-result');
      box.innerHTML = `
        <div class="banner banner-ok">
          Generated <b>${res.generated.length}</b> document(s); Skipped <b>${res.skipped.length}</b>.
          ${res.zip_token ? `<a class="btn btn-sm btn-primary" style="margin-left:10px;" href="/api/method/kesari_jefs.api.download_generated_artifact?token=${encodeURIComponent(res.zip_token)}">Download Joining Kit ZIP</a>` : ''}
          ${res.skipped.length ? `<div class="muted" style="margin-top:6px;">Skipped: ${esc(res.skipped.map((s) => `${s.employee_code} ${s.doc_type}: ${s.reason}`).join(' | '))}</div>` : ''}
        </div>`;
    } catch (e) { toast(e.message, true); }
  };

  window._generateIdSheet = async () => {
    const codes = Array.from(document.querySelectorAll('.kit-chk:checked')).map((c) => c.value);
    if (!codes.length) return toast('Select employees first', true);
    try {
      const res = await api('generate_id_card_sheet', { employee_codes_json: codes }, true);
      window.open(`/api/method/kesari_jefs.api.download_generated_artifact?token=${encodeURIComponent(res.file_token)}`, '_blank');
      toast(`ID Card sheet generated (${res.count} cards)`);
    } catch (e) { toast(e.message, true); }
  };

  // 5. EXITS & F&F
  async function renderFnF() {
    setHeader('Exits & Full & Final Settlement', 'Formula-transparent F&F engine with maker-checker approval & auto Service Certificate', `
      <a class="btn" href="/api/method/kesari_jefs.api.export_fnf_excel">Export Client F&amp;F Excel</a>
    `);
    const data = await api('list_fnf_settlements');
    const rows = data.settlements.map((f) => `
      <tr>
        <td class="mono">${esc(f.name)}</td>
        <td><b>${esc(f.employee_code)}</b> · ${esc(f.employee_name)}</td>
        <td>v${f.version}</td>
        <td><span class="pill ${f.status === 'APPROVED' ? 'pill-ok' : f.status === 'SUBMITTED' ? 'pill-warn' : 'pill-neutral'}">${esc(f.status)}</span></td>
        <td>${esc(f.payment_due_date)} ${f.is_overdue && f.status !== 'APPROVED' ? '<span class="pill pill-err">Overdue</span>' : ''}</td>
        <td class="num"><b>${inr(f.net_payable_rupees)}</b></td>
        <td><button class="btn btn-sm btn-primary" onclick="window._openFnf('${esc(f.name)}')">Open</button></td>
      </tr>`).join('');

    const uninit = data.uninitiated_exits.map((u) => `
      <tr>
        <td><b>${esc(u.employee_code)}</b> · ${esc(u.full_name)}</td>
        <td>${esc(u.date_of_exit)}</td>
        <td>${esc(u.client_site)}</td>
        <td><button class="btn btn-sm btn-primary" onclick="window._initFnf('${esc(u.employee_code)}')">Initiate F&amp;F</button></td>
      </tr>`).join('');

    let detailHtml = '';
    if (state.activeFnf) {
      const d = state.activeFnf;
      const f = d.fnf;
      const lines = (f.lines || []).map((l) => `
        <tr>
          <td><span class="pill ${l.line_type === 'EARNING' ? 'pill-ok' : 'pill-err'}">${l.line_type}</span> ${esc(l.label)}</td>
          <td class="mono">${esc(l.formula_text)}</td>
          <td class="num"><b>${inr(l.amount_rupees)}</b></td>
          <td>${l.is_manual && f.status === 'DRAFT' ? `<button class="btn btn-sm btn-danger" onclick="window._delFnfLine('${f.name}','${l.name}')">✕</button>` : ''}</td>
        </tr>`).join('');

      const docsHtml = (d.documents || []).map((doc) => `
        <a class="btn btn-sm" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(doc.name)}">${esc(doc.doc_type)} (${esc(doc.ref_no)})</a>
      `).join(' ');

      detailHtml = `
        <div class="card" style="border-color:#1b3b6f;">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:10px;">
            <div>
              <h3>${esc(f.employee_name)} (${esc(f.employee_code)}) — ${esc(f.name)} v${f.version}</h3>
              <div class="muted">Tenure: <b>${esc(f.tenure_display)}</b> (Counted: ${f.counted_years} yrs) · Site: ${esc(f.client_site)} · Due: ${esc(f.payment_due_date)}</div>
            </div>
            <div style="text-align:right;">
              <div class="muted">Net Payable</div>
              <div style="font-size:24px;font-weight:800;color:#0f294a;">${inr(f.net_payable_rupees)}</div>
              <div class="muted">${esc(d.net_words)}</div>
            </div>
          </div>
          ${d.errors.length ? `<div class="banner banner-err">${esc(d.errors.join(' | '))}</div>` : ''}
          ${d.warnings.length ? `<div class="banner banner-warn">${esc(d.warnings.join(' | '))}</div>` : ''}
          ${f.status === 'APPROVED' ? `<div class="banner banner-ok">Approved &amp; Locked by ${esc(f.approved_by)}. Service Certificate generated automatically! ${docsHtml}</div>` : ''}
          <div class="table-wrap"><table><thead><tr><th>Component</th><th>Formula</th><th class="num">Amount</th><th></th></tr></thead><tbody>${lines}</tbody></table></div>
          ${f.status === 'DRAFT' ? `
            <div class="form-row" style="margin-top:12px;">
              <div><label>Manual Code</label><select id="ml-code"><option>ARREARS</option><option>NOTICE_RECOVERY</option><option>ADVANCE</option><option>OTHER</option></select></div>
              <div><label>Type</label><select id="ml-type"><option>EARNING</option><option>DEDUCTION</option></select></div>
              <div><label>Amount (₹)</label><input type="number" id="ml-amt" value="500" /></div>
              <div><label>Note</label><input type="text" id="ml-note" placeholder="Uniform / arrears" /></div>
              <div style="display:flex;align-items:flex-end;"><button class="btn" onclick="window._addFnfLine('${f.name}')">+ Add Line</button></div>
            </div>` : ''}
          <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">
            ${f.status === 'DRAFT' ? `<button class="btn" onclick="window._recalcFnf('${f.name}')">Recalculate</button><button class="btn btn-primary" onclick="window._submitFnf('${f.name}')">Submit for Approval</button>` : ''}
            ${f.status === 'SUBMITTED' ? `<button class="btn btn-success" onclick="window._approveFnf('${f.name}')">Approve &amp; Lock (+ Service Cert)</button><button class="btn btn-danger" onclick="window._rejectFnf('${f.name}')">Reject to Draft</button>` : ''}
            ${f.status === 'APPROVED' ? `<button class="btn" onclick="window._reviseFnf('${f.name}')">Create Revised Version</button>` : ''}
          </div>
        </div>`;
    }

    document.getElementById('view-content').innerHTML = `
      ${detailHtml}
      ${uninit ? `<div class="card"><h3>Exited Employees Pending F&amp;F</h3><table><thead><tr><th>Employee</th><th>Exit Date</th><th>Site</th><th></th></tr></thead><tbody>${uninit}</tbody></table></div>` : ''}
      <div class="card">
        <h3>F&amp;F Settlements</h3>
        <div class="table-wrap"><table><thead><tr><th>ID</th><th>Employee</th><th>Ver</th><th>Status</th><th>Due Date</th><th class="num">Net Payable</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="7" class="muted">No F&amp;F settlements yet. Record an exit from Employees tab.</td></tr>'}</tbody></table></div>
      </div>`;
  }

  window._initFnf = async (code) => { try { state.activeFnf = await api('initiate_fnf', { employee_code: code }, true); renderFnF(); } catch (e) { toast(e.message, true); } };
  window._openFnf = async (id) => { try { state.activeFnf = await api('get_fnf_detail', { fnf_id: id }); renderFnF(); } catch (e) { toast(e.message, true); } };
  window._recalcFnf = async (id) => { try { state.activeFnf = await api('recalculate_fnf', { fnf_id: id }, true); toast('Recalculated'); renderFnF(); } catch (e) { toast(e.message, true); } };
  window._addFnfLine = async (id) => {
    try {
      state.activeFnf = await api('add_fnf_manual_line', {
        fnf_id: id,
        code: document.getElementById('ml-code').value,
        line_type: document.getElementById('ml-type').value,
        amount_rupees: document.getElementById('ml-amt').value,
        note: document.getElementById('ml-note').value,
      }, true);
      renderFnF();
    } catch (e) { toast(e.message, true); }
  };
  window._delFnfLine = async (id, line) => { try { state.activeFnf = await api('delete_fnf_manual_line', { fnf_id: id, line_name: line }, true); renderFnF(); } catch (e) { toast(e.message, true); } };
  window._submitFnf = async (id) => { try { state.activeFnf = await api('submit_fnf', { fnf_id: id }, true); toast('Submitted for Approver review'); renderFnF(); } catch (e) { toast(e.message, true); } };
  window._approveFnf = async (id) => { try { state.activeFnf = await api('approve_fnf', { fnf_id: id, remarks: 'Approved' }, true); toast('F&F Approved & Service Certificate generated!'); renderFnF(); } catch (e) { toast(e.message, true); } };
  window._rejectFnf = async (id) => { try { state.activeFnf = await api('reject_fnf', { fnf_id: id, remarks: 'Returned for review' }, true); toast('Returned to Draft'); renderFnF(); } catch (e) { toast(e.message, true); } };
  window._reviseFnf = async (id) => { try { state.activeFnf = await api('revise_fnf', { fnf_id: id }, true); toast('Created new revision draft'); renderFnF(); } catch (e) { toast(e.message, true); } };

  // 6. SERVICE CERTIFICATES
  async function renderCertificates() {
    setHeader('Service Certificates', 'Auto-generated upon F&F approval');
    const docs = await api('list_documents', { doc_type: 'SERVICE_CERTIFICATE' });
    const rows = docs.map((d) => `
      <tr>
        <td class="mono">${esc(d.ref_no)}</td>
        <td><b>${esc(d.employee_code)}</b> · ${esc(d.employee_name)}</td>
        <td>v${d.version}</td>
        <td>${esc(String(d.generated_at).slice(0, 16))}</td>
        <td>${d.is_void ? '<span class="pill pill-err">VOID</span>' : '<span class="pill pill-ok">Active</span>'}</td>
        <td><a class="btn btn-sm btn-primary" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(d.name)}">Download PDF</a></td>
      </tr>`).join('');
    document.getElementById('view-content').innerHTML = `<div class="card"><div class="table-wrap"><table><thead><tr><th>Ref No</th><th>Employee</th><th>Ver</th><th>Generated</th><th>Status</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="6" class="muted">No service certificates generated yet (approve an F&amp;F settlement first).</td></tr>'}</tbody></table></div></div>`;
  }

  // 7. WAGE REVISION
  async function renderWageRevision() {
    setHeader('Minimum Wages & Increment Letters', 'April / October statutory revisions + Gujarati increment letter batch');
    const [rates, revs, settings] = await Promise.all([api('list_min_wages'), api('list_wage_revisions'), api('get_settings_data')]);

    const rateRows = rates.map((r) => `<tr><td>${esc(r.state)}</td><td>${esc(r.zone)}</td><td>${esc(r.skill_category)}</td><td>${esc(r.effective_from)}</td><td class="num">${inr(Math.round(r.total_paise/100))}</td><td class="muted">${esc(r.source_reference)}</td></tr>`).join('');
    const revRows = revs.map((r) => `<tr><td class="mono">${esc(r.name)}</td><td><b>${esc(r.revision_name)}</b></td><td>${esc(r.effective_from)}</td><td>${esc(r.policy)}</td><td><span class="pill ${r.status==='APPROVED'?'pill-ok':'pill-warn'}">${esc(r.status)}</span></td><td><button class="btn btn-sm btn-primary" onclick="window._openRev('${esc(r.name)}')">Open Grid</button></td></tr>`).join('');

    let revDetailHtml = '';
    if (state.activeRevision) {
      const rv = state.activeRevision;
      const itemsHtml = (rv.items || []).map((it) => `
        <tr>
          <td><b>${esc(it.employee_code)}</b> · ${esc(it.employee_name)}</td>
          <td>${esc(it.skill_category)}</td>
          <td class="num">${inr(Math.round(it.old_total_paise/100))}</td>
          <td class="num">${inr(Math.round(it.min_wage_paise/100))}</td>
          <td class="num">${rv.status === 'DRAFT' ? `<input type="number" style="width:100px" value="${Math.round(it.proposed_total_paise/100)}" onchange="window._editRevItem('${rv.name}','${it.name}',this.value)" />` : inr(Math.round(it.proposed_total_paise/100))}</td>
          <td class="num">${inr(Math.round(it.delta_paise/100))}</td>
          <td>${it.needs_letter ? '<span class="pill pill-ok">Yes</span>' : '<span class="pill pill-neutral">No</span>'}</td>
          <td class="muted">${esc(it.reason)}</td>
        </tr>`).join('');
      revDetailHtml = `
        <div class="card" style="border-color:#2563eb;">
          <h3>Revision Grid: ${esc(rv.revision_name)} (${esc(rv.status)})</h3>
          <div class="table-wrap"><table><thead><tr><th>Employee</th><th>Skill</th><th class="num">Old</th><th class="num">Min Wage</th><th class="num">Proposed</th><th class="num">Δ</th><th>Letter</th><th>Reason</th></tr></thead><tbody>${itemsHtml}</tbody></table></div>
          <div style="display:flex;gap:8px;margin-top:12px;">
            ${rv.status === 'DRAFT' ? `<button class="btn btn-success" onclick="window._approveRev('${rv.name}')">Approve &amp; Generate Increment Letters</button>` : ''}
            <a class="btn" href="/api/method/kesari_jefs.api.export_wage_revision_excel?revision_id=${encodeURIComponent(rv.name)}">Export Revised Wages (.xlsx)</a>
          </div>
          <div id="rev-zip-box" style="margin-top:8px;"></div>
        </div>`;
    }

    const watcherRows = (settings.watcher_sources || []).map((w) => `<tr><td>${esc(w.state)}</td><td class="mono">${esc(w.url)}</td><td>${esc(w.last_status)}</td><td>${esc(w.last_checked_at || '-')}</td></tr>`).join('');

    document.getElementById('view-content').innerHTML = `
      ${revDetailHtml}
      <div class="grid-2">
        <div class="card">
          <h3>Create Wage Revision Run</h3>
          <div class="form-row">
            <div><label>Name</label><input type="text" id="wr-name" value="April 2027 Revision" /></div>
            <div><label>Effective From</label><input type="date" id="wr-eff" value="2027-04-01" /></div>
            <div><label>Policy</label><select id="wr-pol"><option value="RAISE_TO_MIN">Raise to Minimum Only</option><option value="ADD_VDA_DELTA">Add VDA Delta to All</option><option value="CUSTOM_PCT">Custom %</option></select></div>
            <div><label>VDA Delta (₹) / %</label><input type="number" id="wr-val" value="0" /></div>
          </div>
          <button class="btn btn-primary" onclick="window._createRev()">Propose Revision</button>
          <h4 style="margin-top:14px;">Revision Runs</h4>
          <div class="table-wrap"><table><thead><tr><th>ID</th><th>Name</th><th>Eff</th><th>Policy</th><th>Status</th><th></th></tr></thead><tbody>${revRows || '<tr><td colspan="6" class="muted">None yet</td></tr>'}</tbody></table></div>
        </div>
        <div class="card">
          <h3>Minimum Wage Rates</h3>
          <div class="form-row">
            <div><label>State</label><input type="text" id="mw-st" value="Gujarat" /></div>
            <div><label>Zone</label><input type="text" id="mw-zn" value="Zone-A" /></div>
            <div><label>Skill</label><select id="mw-sk"><option>Unskilled</option><option>Semi-Skilled</option><option>Skilled</option><option>Highly Skilled</option></select></div>
            <div><label>Eff Date</label><input type="date" id="mw-eff" value="2027-04-01" /></div>
            <div><label>Basic (₹)</label><input type="number" id="mw-b" value="12500" /></div>
            <div><label>VDA (₹)</label><input type="number" id="mw-v" value="2500" /></div>
          </div>
          <button class="btn btn-sm btn-primary" onclick="window._addMinWage()">+ Add Rate</button>
          <div class="table-wrap" style="margin-top:10px;max-height:220px;overflow:auto;"><table><thead><tr><th>State</th><th>Zone</th><th>Skill</th><th>Eff</th><th class="num">Total</th><th>Source</th></tr></thead><tbody>${rateRows}</tbody></table></div>
          <h4 style="margin-top:12px;">Minimum Wage Watcher (Alert Only)</h4>
          <table><thead><tr><th>State</th><th>URL</th><th>Status</th><th>Checked</th></tr></thead><tbody>${watcherRows}</tbody></table>
          <button class="btn btn-sm" style="margin-top:8px;" onclick="window._runWatcher()">Check Official Pages Now</button>
        </div>
      </div>`;
  }

  window._addMinWage = async () => {
    try {
      await api('save_min_wage', {
        state: document.getElementById('mw-st').value, zone: document.getElementById('mw-zn').value,
        skill_category: document.getElementById('mw-sk').value, effective_from: document.getElementById('mw-eff').value,
        basic_rupees: document.getElementById('mw-b').value, vda_rupees: document.getElementById('mw-v').value,
        source_reference: 'Manual HR entry',
      }, true);
      toast('Minimum wage rate saved');
      renderWageRevision();
    } catch (e) { toast(e.message, true); }
  };
  window._createRev = async () => {
    try {
      const val = document.getElementById('wr-val').value;
      const pol = document.getElementById('wr-pol').value;
      state.activeRevision = await api('create_wage_revision', {
        revision_name: document.getElementById('wr-name').value,
        effective_from: document.getElementById('wr-eff').value,
        policy: pol,
        vda_delta_rupees: pol === 'ADD_VDA_DELTA' ? val : 0,
        custom_pct: pol === 'CUSTOM_PCT' ? val : 0,
      }, true);
      toast('Revision proposals created');
      renderWageRevision();
    } catch (e) { toast(e.message, true); }
  };
  window._openRev = async (id) => { state.activeRevision = await api('get_wage_revision', { revision_id: id }); renderWageRevision(); };
  window._editRevItem = async (rid, iid, val) => {
    try {
      state.activeRevision = await api('update_revision_item', { revision_id: rid, item_name: iid, proposed_rupees: val }, true);
      renderWageRevision();
    } catch (e) { toast(e.message, true); }
  };
  window._approveRev = async (rid) => {
    try {
      const res = await api('approve_wage_revision', { revision_id: rid }, true);
      state.activeRevision = res.revision;
      toast(`Approved & generated ${res.generated.length} Increment Letter(s)`);
      await renderWageRevision();
      if (res.zip_token) {
        document.getElementById('rev-zip-box').innerHTML = `<a class="btn btn-primary btn-sm" href="/api/method/kesari_jefs.api.download_generated_artifact?token=${encodeURIComponent(res.zip_token)}">Download Increment Letters ZIP</a>`;
      }
    } catch (e) { toast(e.message, true); }
  };
  window._runWatcher = async () => { try { await api('run_watcher_check', {}, true); toast('Watcher check completed'); renderWageRevision(); } catch (e) { toast(e.message, true); } };

  // 8. DOCUMENTS REGISTER
  async function renderDocuments() {
    setHeader('Documents Register', 'Every generated document with unique Ref No, SHA-256 & audited download count');
    const q = document.getElementById('doc-q')?.value || '';
    const docs = await api('list_documents', { q });
    const rows = docs.map((d) => `
      <tr>
        <td class="mono"><b>${esc(d.ref_no)}</b></td>
        <td>${esc(d.doc_type)}</td>
        <td>${esc(d.employee_code)} · ${esc(d.employee_name)}</td>
        <td>v${d.version}</td>
        <td>${esc(d.generated_by)}<br/><span class="muted">${esc(String(d.generated_at).slice(0, 16))}</span></td>
        <td>${d.downloaded_count}</td>
        <td>${d.is_void ? `<span class="pill pill-err" title="${esc(d.void_reason)}">VOID</span>` : '<span class="pill pill-ok">Valid</span>'}</td>
        <td>
          <a class="btn btn-sm" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(d.name)}&fmt=pdf">PDF</a>
          <a class="btn btn-sm" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(d.name)}&fmt=docx">DOCX</a>
          ${!d.is_void ? `<button class="btn btn-sm btn-danger" onclick="window._voidDoc('${esc(d.name)}')">Void</button>` : ''}
        </td>
      </tr>`).join('');
    document.getElementById('view-content').innerHTML = `
      <div class="card">
        <div class="form-row">
          <div><input type="text" id="doc-q" value="${esc(q)}" placeholder="Search ref no, employee, doc type..." /></div>
          <div><button class="btn btn-primary" onclick="window._reloadDocs()">Search</button></div>
        </div>
        <div class="table-wrap"><table><thead><tr><th>Ref No</th><th>Type</th><th>Employee</th><th>Ver</th><th>Generated</th><th>DL</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows || '<tr><td colspan="8" class="muted">No documents generated yet.</td></tr>'}</tbody></table></div>
      </div>`;
  }
  window._reloadDocs = () => renderDocuments();
  window._voidDoc = async (id) => {
    const r = prompt('Reason for voiding document:');
    if (!r) return;
    try { await api('void_document', { doc_id: id, reason: r }, true); toast('Document voided'); renderDocuments(); } catch (e) { toast(e.message, true); }
  };

  // 9. REPORTS
  async function renderReports() {
    setHeader('Reports', 'Formula-injection-safe Excel exports');
    const items = [
      ['joiners', 'Joiners Register'],
      ['exits', 'Exits Register'],
      ['documents-generated', 'Documents Generated'],
      ['fnf-register', 'F&F Register'],
      ['pending-fnf', 'Pending F&F (2-Working-Day Deadline)'],
      ['missing-data', 'Missing Data / Blocked Kits'],
      ['wage-revision', 'Wage Revisions'],
    ];
    document.getElementById('view-content').innerHTML = `
      <div class="grid-4">
        ${items.map(([k, title]) => `<div class="card"><h3>${title}</h3><a class="btn btn-primary btn-sm" href="/api/method/kesari_jefs.api.download_report?report_type=${k}">Download .xlsx</a></div>`).join('')}
        <div class="card"><h3>Client F&amp;F Workbook</h3><a class="btn btn-primary btn-sm" href="/api/method/kesari_jefs.api.export_fnf_excel">Download .xlsx</a></div>
      </div>`;
  }

  // 10. SETTINGS & AUDIT
  async function renderSettings() {
    setHeader('Settings, Templates & Audit Log', 'Company letterhead, .docx templates, effective-dated statutory rules & client sites');
    const data = await api('get_settings_data');
    const tab = state.settingsTab;
    const tabsHtml = ['company', 'templates', 'statutory', 'sites', 'users', 'audit'].map((t) => `
      <button class="tab-btn ${tab === t ? 'active' : ''}" onclick="window._setTab('${t}')">${t.toUpperCase()}</button>`).join('');

    let bodyHtml = '';
    if (tab === 'company') {
      const c = data.company;
      bodyHtml = `
        <div class="card">
          <div class="form-row">
            <div><label>Legal Name</label><input type="text" id="co-name" value="${esc(c.legal_name)}" /></div>
            <div><label>Ref Prefix</label><input type="text" id="co-pref" value="${esc(c.ref_prefix)}" /></div>
            <div><label>Signatory Name</label><input type="text" id="co-sig" value="${esc(c.signatory_name)}" /></div>
            <div><label>Signatory Designation</label><input type="text" id="co-desg" value="${esc(c.signatory_designation)}" /></div>
            <div><label>Phone</label><input type="text" id="co-ph" value="${esc(c.phone)}" /></div>
            <div><label>Email</label><input type="text" id="co-em" value="${esc(c.email)}" /></div>
            <div><label>PF Code</label><input type="text" id="co-pf" value="${esc(c.pf_code)}" /></div>
            <div><label>ESI Code</label><input type="text" id="co-esi" value="${esc(c.esi_code)}" /></div>
          </div>
          <label>Address</label><textarea id="co-addr" rows="2">${esc(c.address)}</textarea>
          <button class="btn btn-primary" style="margin-top:10px;" onclick="window._saveCompany()">Save Company Profile</button>
        </div>`;
    } else if (tab === 'templates') {
      const tRows = data.templates.map((t) => `
        <tr>
          <td><b>${esc(t.doc_type)}</b></td>
          <td>${esc(t.template_name)}</td>
          <td>v${t.version} (${t.engine})</td>
          <td class="mono">${esc((JSON.parse(t.placeholders_json||'[]')).slice(0,8).join(', '))}</td>
          <td>${t.is_active ? '<span class="pill pill-ok">Active</span>' : '<button class="btn btn-sm" onclick="window._actTpl(\''+esc(t.name)+'\')">Activate</button>'}</td>
          <td><button class="btn btn-sm" onclick="window._prevTpl('${esc(t.name)}')">Preview PDF</button></td>
        </tr>`).join('');
      bodyHtml = `
        <div class="card">
          <h3>Upload Editable .docx Template</h3>
          <div class="form-row">
            <div><label>Doc Type</label><select id="tpl-type"><option>OFFER_LETTER</option><option>APPOINTMENT_LETTER</option><option>GRATUITY_FORM_F</option><option>EPFO_FORM_2</option><option>POLICE_VERIFICATION</option><option>INCREMENT_LETTER</option><option>SERVICE_CERTIFICATE</option></select></div>
            <div><label>Template Name</label><input type="text" id="tpl-name" value="Custom Client Format" /></div>
            <div><label>.docx File</label><input type="file" id="tpl-file" accept=".docx" /></div>
            <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" onclick="window._uploadTpl()">Upload &amp; Validate</button></div>
          </div>
          <div class="table-wrap"><table><thead><tr><th>Type</th><th>Name</th><th>Ver</th><th>Placeholders</th><th>Active</th><th>Preview</th></tr></thead><tbody>${tRows}</tbody></table></div>
          <details style="margin-top:12px;"><summary style="cursor:pointer;font-weight:600;">Allowed Field Dictionary (${Object.keys(data.placeholders).length} fields)</summary>
            <div class="mono" style="margin-top:8px;">${Object.entries(data.placeholders).map(([k,v]) => `<div><b>{{${k}}}</b> — ${esc(v)}</div>`).join('')}</div>
          </details>
        </div>`;
    } else if (tab === 'statutory') {
      const sRows = data.statutory.map((s) => `<tr><td class="mono">${esc(s.setting_key)}</td><td><b>${esc(s.setting_value)}</b></td><td>${esc(s.effective_from)}</td><td class="muted">${esc(s.note)}</td></tr>`).join('');
      bodyHtml = `
        <div class="card">
          <h3>Add Effective-Dated Statutory Value</h3>
          <div class="form-row">
            <div><label>Key</label><input type="text" id="st-k" placeholder="bonus.company_pct" /></div>
            <div><label>Value</label><input type="text" id="st-v" placeholder="8.33" /></div>
            <div><label>Effective From</label><input type="date" id="st-d" value="2026-04-01" /></div>
            <div><label>Note</label><input type="text" id="st-n" placeholder="Source notification" /></div>
          </div>
          <button class="btn btn-primary btn-sm" onclick="window._saveStat()">Add Setting</button>
          <div class="table-wrap" style="margin-top:12px;"><table><thead><tr><th>Key</th><th>Value</th><th>Effective From</th><th>Source / Note</th></tr></thead><tbody>${sRows}</tbody></table></div>
        </div>`;
    } else if (tab === 'sites') {
      const srRows = data.site_rules.map((r) => `<tr><td><b>${esc(r.site_code)}</b></td><td>${esc(r.site_name)}</td><td>${r.include_bonus?'Yes':'No'}</td><td>${r.include_leave?'Yes':'No'}</td><td>${r.include_gratuity?'Yes':'No'}</td><td class="muted">${esc(r.notes)}</td></tr>`).join('');
      bodyHtml = `
        <div class="card">
          <h3>Client Site F&amp;F Rules (CONMAT / EXECHON / SAT)</h3>
          <div class="form-row">
            <div><label>Site Code</label><input type="text" id="sr-c" placeholder="CONMAT" /></div>
            <div><label>Site Name</label><input type="text" id="sr-n" placeholder="Principal Employer" /></div>
            <div><label>Bonus?</label><select id="sr-b"><option value="1">Yes</option><option value="0">No</option></select></div>
            <div><label>Leave?</label><select id="sr-l"><option value="1">Yes</option><option value="0">No</option></select></div>
            <div><label>Gratuity?</label><select id="sr-g"><option value="1">Yes</option><option value="0">No</option></select></div>
          </div>
          <button class="btn btn-primary btn-sm" onclick="window._saveSite()">Save Site Rule</button>
          <div class="table-wrap" style="margin-top:12px;"><table><thead><tr><th>Code</th><th>Name</th><th>Bonus</th><th>Leave</th><th>Gratuity</th><th>Rule Notes</th></tr></thead><tbody>${srRows}</tbody></table></div>
        </div>`;
    } else if (tab === 'users') {
      bodyHtml = `
        <div class="card">
          <h3>Seeded Role-Based Users (Maker-Checker Ready)</h3>
          <p class="muted">Use <b>approver@kesari.local</b> (password: <code>Kesari@2026</code>) when approving F&amp;F or Wage Revisions prepared by another account.</p>
          <table><thead><tr><th>Email</th><th>Role</th><th>Capabilities</th></tr></thead><tbody>
            <tr><td>Administrator</td><td>JEFS Admin</td><td>Full access, templates, statutory settings, void docs, PII reveal</td></tr>
            <tr><td>onboarding@kesari.local</td><td>JEFS HR Onboarding</td><td>Employee upload, photos, nominees, Joining Kit &amp; Police Letter</td></tr>
            <tr><td>payroll@kesari.local</td><td>JEFS Payroll Specialist</td><td>Salary upload, min wages, wage revision proposals</td></tr>
            <tr><td>exitdesk@kesari.local</td><td>JEFS Exit Desk</td><td>Bonus/Leave upload, Exits, F&amp;F preparation &amp; submit</td></tr>
            <tr><td>approver@kesari.local</td><td>JEFS Approver</td><td>Approve/reject F&amp;F (triggers Service Cert) &amp; Wage Revisions</td></tr>
            <tr><td>auditor@kesari.local</td><td>JEFS Auditor</td><td>Read-only access to reports &amp; append-only Audit Log</td></tr>
          </tbody></table>
        </div>`;
    } else {
      const logs = await api('list_audit_logs', { limit: 100 });
      const lRows = logs.map((l) => `<tr><td class="mono">${esc(String(l.logged_at).slice(0, 19))}</td><td>${esc(l.user_id)}</td><td><b>${esc(l.action)}</b></td><td>${esc(l.entity)}</td><td class="mono">${esc(l.entity_id)}</td><td class="mono">${esc((l.after_json||'').slice(0,120))}</td></tr>`).join('');
      bodyHtml = `<div class="card"><h3>Append-Only Audit Log</h3><div class="table-wrap"><table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Entity</th><th>ID</th><th>Details</th></tr></thead><tbody>${lRows}</tbody></table></div></div>`;
    }

    document.getElementById('view-content').innerHTML = `<div class="tabs">${tabsHtml}</div>${bodyHtml}`;
  }

  window._setTab = (t) => { state.settingsTab = t; renderSettings(); };
  window._saveCompany = async () => {
    try {
      await api('save_company_profile', {
        data_json: {
          legal_name: document.getElementById('co-name').value,
          ref_prefix: document.getElementById('co-pref').value,
          signatory_name: document.getElementById('co-sig').value,
          signatory_designation: document.getElementById('co-desg').value,
          phone: document.getElementById('co-ph').value,
          email: document.getElementById('co-em').value,
          pf_code: document.getElementById('co-pf').value,
          esi_code: document.getElementById('co-esi').value,
          address: document.getElementById('co-addr').value,
        },
      }, true);
      toast('Company profile saved');
    } catch (e) { toast(e.message, true); }
  };
  window._uploadTpl = async () => {
    const f = document.getElementById('tpl-file').files[0];
    if (!f) return toast('Choose a .docx file', true);
    const fd = new FormData();
    fd.append('doc_type', document.getElementById('tpl-type').value);
    fd.append('template_name', document.getElementById('tpl-name').value);
    fd.append('file', f);
    try { await apiUpload('upload_docx_template', fd); toast('Template uploaded & validated'); renderSettings(); } catch (e) { toast(e.message, true); }
  };
  window._actTpl = async (id) => { try { await api('activate_template', { template_id: id }, true); toast('Template activated'); renderSettings(); } catch (e) { toast(e.message, true); } };
  window._prevTpl = async (id) => {
    const code = prompt('Employee Code for preview (e.g. KM1023):');
    if (!code) return;
    try {
      const res = await api('preview_template', { template_id: id, employee_code: code }, true);
      window.open(`/api/method/kesari_jefs.api.download_generated_artifact?token=${encodeURIComponent(res.file_token)}`, '_blank');
    } catch (e) { toast(e.message, true); }
  };
  window._saveStat = async () => {
    try {
      await api('save_statutory_setting', {
        setting_key: document.getElementById('st-k').value,
        setting_value: document.getElementById('st-v').value,
        effective_from: document.getElementById('st-d').value,
        note: document.getElementById('st-n').value,
      }, true);
      toast('Statutory setting saved');
      renderSettings();
    } catch (e) { toast(e.message, true); }
  };
  window._saveSite = async () => {
    try {
      await api('save_client_site_rule', {
        site_code: document.getElementById('sr-c').value,
        site_name: document.getElementById('sr-n').value,
        include_bonus: document.getElementById('sr-b').value,
        include_leave: document.getElementById('sr-l').value,
        include_gratuity: document.getElementById('sr-g').value,
      }, true);
      toast('Client site rule saved');
      renderSettings();
    } catch (e) { toast(e.message, true); }
  };

  window._jefsNav = loadView;
  loadView('dashboard');
})();
