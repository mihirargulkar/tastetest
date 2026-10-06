async function check(res) {
  if (res.ok) return res;
  const body = await res.json().catch(() => ({}));
  const d = body.detail;
  const msg = typeof d === "string" ? d
    : Array.isArray(d) ? d.map((x) => x.msg).join("; ")
    : d ? JSON.stringify(d) : "";
  throw new Error(msg || `Request failed (${res.status})`);
}

export async function streamPost(url, body, onEvent) {
  const res = await check(await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (chunk.startsWith("data: ")) onEvent(JSON.parse(chunk.slice(6)));
    }
  }
  buf += decoder.decode();
  if (buf.startsWith("data: ")) onEvent(JSON.parse(buf.slice(6)));
}

export const getJSON = async (url) => (await check(await fetch(url))).json();

export const postJSON = async (url, body) => (await check(await fetch(url, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
}))).json();
