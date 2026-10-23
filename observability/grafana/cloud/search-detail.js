import http from 'k6/http';
import { check, fail } from 'k6';

// Render only this approved public API base. No arbitrary URL from response data.
const api = __API_BASE_JSON__;
export const options = {
  maxRedirects: 0,
  httpDebug: '',
  insecureSkipTLSVerify: false,
  systemTags: ['status', 'method', 'name', 'check'],
  userAgent: 'PawLocal-Synthetic-Journey/1',
};

function checkedJson(response, name) {
  if (!check(response, { [name]: (r) => r.status === 200 && typeof r.body === 'string' && r.body.length < 65536 })) {
    fail('Public journey response failed validation');
  }
  try { return response.json(); } catch (_) { fail('Public journey JSON is invalid'); }
}

export default function () {
  const results = checkedJson(http.get(`${api}/places?page_size=1`, {
    timeout: '4s', redirects: 0, tags: { name: '/api/v1/places' },
  }), 'search succeeds');
  const id = results && Array.isArray(results.items) && results.items[0] && results.items[0].id;
  if (!check(id, { 'published place exists': (value) => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) })) {
    fail('No valid published place is available');
  }
  const detail = checkedJson(http.get(`${api}/places/${id}`, {
    timeout: '4s', redirects: 0, tags: { name: '/api/v1/places/{place_id}' },
  }), 'details succeed');
  if (!check(detail, { 'details match result': (value) => value && value.id === id })) {
    fail('Public journey details do not match');
  }
}
