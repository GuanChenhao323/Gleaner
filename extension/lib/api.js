export class ApiError extends Error {
  constructor(code, status = 0) { super(code); this.code = code; this.status = status; }
}
export async function request(cfg, path, body, { login = false, session = false, fetcher = fetch } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const res = await fetcher(cfg.server + path, { method: body === undefined ? 'GET' : 'POST', credentials: 'omit', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(cfg.token ? { Authorization: `Bearer ${cfg.token}` } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!(res.headers.get('content-type') || '').toLowerCase().includes('application/json')) throw new ApiError('invalid_response', res.status);
    let data;
    try { data = await res.json(); } catch { throw new ApiError('invalid_response', res.status); }
    if (!res.ok) throw new ApiError(typeof data?.error === 'string' ? data.error : 'request_failed', res.status);
    if (!data || Array.isArray(data) || typeof data !== 'object') throw new ApiError('invalid_response', res.status);
    if (session) {
      if (!Number.isInteger(data.id) || data.id <= 0 || typeof data.email !== 'string' || !data.email.trim()) throw new ApiError('invalid_session_response');
    } else if (login) {
      if (typeof data.token !== 'string' || !data.token || !Number.isInteger(data.user?.id) || typeof data.user.email !== 'string') throw new ApiError('invalid_login_response');
    } else if (data.schema_version !== 1 || data.ok !== true) throw new ApiError('invalid_response', res.status);
    if (path === '/api/v1/captures' && (!Array.isArray(data.results) || data.request_id !== body.request_id || data.results.length !== body.targets.length || data.results.some((r, i) => r.candidate_id !== body.targets[i].candidate_id || !['new', 'changed', 'unchanged', 'failed'].includes(r.status) || (r.status === 'failed' ? typeof r.error !== 'string' : (!Number.isInteger(r.item_id) || !Number.isInteger(r.monitor_id)))))) throw new ApiError('invalid_capture_response');
    if(path==='/api/v1/web-captures' && body!==undefined) {
      const row=data.results?.[0],ids=body.fragments.map(f=>f.candidate_id);
      if(data.request_id!==body.request_id || !Array.isArray(data.results) || data.results.length!==1 || JSON.stringify(data.candidate_ids)!==JSON.stringify(ids) || row?.candidate_id!=='collection' || !['new','changed','unchanged'].includes(row.status) || !['item_id','source_id','version'].every(k=>Number.isInteger(row[k]) && row[k]>0) || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(row.capture_id || '') || row.fragment_count!==ids.length)throw new ApiError('invalid_capture_response');
    }
    if(['/api/v1/captures','/api/v1/web-captures'].includes(path)&&body?.reading&&data.results?.every(r=>r.status!=='failed')&&(!Number.isInteger(data.reading_source_id)||data.reading_source_id<=0))throw new ApiError('invalid_capture_response');
    if (path.endsWith('/result') && (data.job_id !== Number(path.split('/').at(-2)) || !['changed', 'unchanged', 'failed'].includes(data.status))) throw new ApiError('invalid_result_response');
    if(path==='/api/v1/reading-jobs/claim') {
      const j=data.job;
      if(!(j===null || (Number.isInteger(j?.id)&&j.id>0&&Number.isInteger(j.source_id)&&j.source_id>0&&j.device_id===body.device_id&&typeof j.lease==='string'&&j.lease.length>0&&Number.isInteger(j.revision)&&j.revision>0&&Number.isFinite(j.expires_at)&&j.recipe?.version===1&&typeof j.recipe.url==='string'&&typeof j.recipe.query==='string'&&typeof j.recipe.binding?.account_key==='string'&&['verify','check'].includes(j.purpose))))throw new ApiError('invalid_job_response');
    } else if (path.endsWith('/claim') && !(data.job === null || (Number.isInteger(data.job?.id) && typeof data.job?.lease === 'string' && data.job.lease.length > 0 && Number.isInteger(data.job.monitor_id) && data.job.device_id === body.device_id && typeof data.job.binding?.account_key === 'string' && typeof data.job.recipe?.url === 'string' && typeof data.job.recipe?.selector === 'string' && Number.isFinite(data.job.expires_at) && Number.isInteger(data.job.revision)))) throw new ApiError('invalid_job_response');
    if(path.startsWith('/api/v1/reading-jobs/')&&path.endsWith('/result')&&!['verified','changed','unchanged','need_login','account_unknown','account_mismatch','route_mismatch','view_mismatch','permission_denied','render_timeout','selection_missing','no_match','unsupported','failed','worker_interrupted','preview_only'].includes(data.result))throw new ApiError('invalid_result_response');
    if(path==='/api/v1/reading-devices/heartbeat'&&data.device_id!==body.device_id)throw new ApiError('invalid_response');
    return data;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(e.name === 'AbortError' ? 'backend_timeout' : 'backend_unavailable');
  } finally { clearTimeout(timer); }
}
