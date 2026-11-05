export class ApiError extends Error {
  constructor(code, status = 0) { super(code); this.code = code; this.status = status; }
}
export async function request(cfg, path, body, { login = false, fetcher = fetch } = {}) {
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
    if (login) {
      if (typeof data.token !== 'string' || !data.token || !Number.isInteger(data.user?.id) || typeof data.user.email !== 'string') throw new ApiError('invalid_login_response');
    } else if (data.schema_version !== 1 || data.ok !== true) throw new ApiError('invalid_response', res.status);
    if (path === '/api/v1/captures' && (!Array.isArray(data.results) || data.request_id !== body.request_id || data.results.length !== body.targets.length || data.results.some((r, i) => r.candidate_id !== body.targets[i].candidate_id || !['new', 'changed', 'unchanged', 'failed'].includes(r.status) || (r.status === 'failed' ? typeof r.error !== 'string' : (!Number.isInteger(r.item_id) || !Number.isInteger(r.monitor_id)))))) throw new ApiError('invalid_capture_response');
    if (path.endsWith('/result') && (data.job_id !== Number(path.split('/').at(-2)) || !['changed', 'unchanged', 'failed'].includes(data.status))) throw new ApiError('invalid_result_response');
    if (path.endsWith('/claim') && !(data.job === null || (Number.isInteger(data.job?.id) && typeof data.job?.lease === 'string' && data.job.lease.length > 0 && Number.isInteger(data.job.monitor_id) && data.job.device_id === body.device_id && typeof data.job.binding?.account_key === 'string' && typeof data.job.recipe?.url === 'string' && typeof data.job.recipe?.selector === 'string' && Number.isFinite(data.job.expires_at) && Number.isInteger(data.job.revision)))) throw new ApiError('invalid_job_response');
    return data;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(e.name === 'AbortError' ? 'backend_timeout' : 'backend_unavailable');
  } finally { clearTimeout(timer); }
}
