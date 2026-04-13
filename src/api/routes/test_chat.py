"""
Rota de teste de conversação — sem enviar mensagens reais ao WhatsApp.

Endpoints:
  GET  /test/ui           → Interface HTML interativa
  POST /test/chat         → Envia mensagem e captura todas as respostas do agente
  DELETE /test/chat/{phone} → Reseta conversa (apaga lead + state do banco)
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.agent.runner import run_agent
from src.agent.tools.uazapi import test_capture
from src.db.database import async_session
from src.services.lead_service import LeadService
from src.utils.logger import logger

router = APIRouter(prefix="/test", tags=["test"])


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class TestChatRequest(BaseModel):
    phone: str
    message: str
    message_type: str = "text"


class TestChatResponse(BaseModel):
    messages: list[str]       # todas as mensagens que o agente enviaria ao WhatsApp
    node: str
    intent: str | None
    awaiting: bool
    tags: dict


# ---------------------------------------------------------------------------
# POST /test/chat
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=TestChatResponse)
async def test_chat(body: TestChatRequest):
    """
    Processa uma mensagem pelo agente sem enviar ao WhatsApp.
    Retorna todas as mensagens que seriam enviadas + estado final.
    """
    captured: list[str] = []
    token = test_capture.set(captured)
    try:
        result = await run_agent(
            phone=body.phone,
            message=body.message,
            message_type=body.message_type,
        )
    finally:
        test_capture.reset(token)

    logger.info(
        "TEST_CHAT | phone=%s | node=%s | mensagens_capturadas=%d",
        body.phone,
        result.get("current_node"),
        len(captured),
    )

    return TestChatResponse(
        messages=captured,
        node=result.get("current_node") or "",
        intent=result.get("detected_intent"),
        awaiting=bool(result.get("awaiting_response")),
        tags=dict(result.get("tags") or {}),
    )


# ---------------------------------------------------------------------------
# DELETE /test/chat/{phone}
# ---------------------------------------------------------------------------

@router.delete("/chat/{phone}")
async def reset_conversation(phone: str):
    """
    Apaga o lead do banco para reiniciar a conversa do zero.
    """
    async with async_session() as session:
        lead_svc = LeadService(session)
        lead = await lead_svc.get_by_phone(phone)
        if lead:
            await session.delete(lead)
            await session.commit()
            logger.info("TEST_CHAT | Lead resetado | phone=%s | lead_id=%s", phone, lead.id)
            return {"reset": True, "phone": phone}

    return {"reset": False, "phone": phone, "detail": "Lead não encontrado"}


# ---------------------------------------------------------------------------
# GET /test/ui  — Interface HTML
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Agente Marina — Teste</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #e5ddd5;
    height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .container {
    width: 100%;
    max-width: 480px;
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: #fff;
    box-shadow: 0 2px 12px rgba(0,0,0,.2);
  }
  header {
    background: #075e54;
    color: #fff;
    padding: 14px 18px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  header .avatar {
    width: 40px; height: 40px;
    border-radius: 50%;
    background: #25d366;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px;
  }
  header h1 { font-size: 17px; font-weight: 600; }
  header p  { font-size: 12px; opacity: .8; }
  .toolbar {
    background: #f0f0f0;
    padding: 8px 12px;
    display: flex;
    gap: 8px;
    align-items: center;
    border-bottom: 1px solid #ddd;
  }
  .toolbar input {
    flex: 1;
    padding: 6px 10px;
    border: 1px solid #ccc;
    border-radius: 20px;
    font-size: 13px;
    outline: none;
  }
  .toolbar button {
    padding: 6px 14px;
    border: none;
    border-radius: 20px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
  }
  .btn-reset { background: #e74c3c; color: #fff; }
  .btn-reset:hover { background: #c0392b; }
  .chat-area {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    background: #e5ddd5;
  }
  .bubble {
    max-width: 80%;
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 14px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
    position: relative;
  }
  .bubble.user {
    align-self: flex-end;
    background: #dcf8c6;
    border-bottom-right-radius: 2px;
  }
  .bubble.agent {
    align-self: flex-start;
    background: #fff;
    border-bottom-left-radius: 2px;
    box-shadow: 0 1px 2px rgba(0,0,0,.1);
  }
  .bubble .meta {
    font-size: 11px;
    color: #888;
    margin-top: 4px;
    text-align: right;
  }
  .status-bar {
    background: #f9f9f9;
    border-top: 1px solid #eee;
    padding: 6px 14px;
    font-size: 11px;
    color: #555;
    min-height: 26px;
  }
  .input-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    background: #f0f0f0;
    border-top: 1px solid #ddd;
  }
  .input-row textarea {
    flex: 1;
    border: none;
    border-radius: 20px;
    padding: 10px 16px;
    font-size: 14px;
    resize: none;
    outline: none;
    max-height: 120px;
    background: #fff;
    line-height: 1.4;
  }
  .input-row button {
    width: 44px; height: 44px;
    border-radius: 50%;
    border: none;
    background: #075e54;
    color: #fff;
    cursor: pointer;
    font-size: 20px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .input-row button:hover { background: #128c7e; }
  .input-row button:disabled { background: #aaa; cursor: not-allowed; }
  .typing { font-style: italic; color: #888; font-size: 13px; }
  .tag-pill {
    display: inline-block;
    background: #eaf4fb;
    color: #2980b9;
    border-radius: 12px;
    padding: 2px 8px;
    font-size: 11px;
    margin: 2px;
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="avatar">🏠</div>
    <div>
      <h1>Marina — Casa Andréia Perez</h1>
      <p id="headerStatus">Agente de IA · Modo Teste</p>
    </div>
  </header>

  <div class="toolbar">
    <input id="phoneInput" type="text" placeholder="Telefone do lead (ex: 5565999999999)" value="5565999999999" />
    <button class="btn-reset" onclick="resetConversation()">⟳ Resetar</button>
  </div>

  <div class="chat-area" id="chatArea"></div>

  <div class="status-bar" id="statusBar">
    Node: — &nbsp;|&nbsp; Aguardando resposta: —
  </div>

  <div class="input-row">
    <textarea id="msgInput" rows="1" placeholder="Digite uma mensagem..." onkeydown="handleKey(event)"></textarea>
    <button id="sendBtn" onclick="sendMessage()">➤</button>
  </div>
</div>

<script>
  const API = "";  // mesmo origin

  function getPhone() {
    return document.getElementById("phoneInput").value.trim() || "5565999999999";
  }

  function now() {
    return new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }

  function appendBubble(text, type, meta) {
    const area = document.getElementById("chatArea");
    const div = document.createElement("div");
    div.className = `bubble ${type}`;
    div.textContent = text;
    if (meta) {
      const m = document.createElement("div");
      m.className = "meta";
      m.textContent = meta;
      div.appendChild(m);
    }
    area.appendChild(div);
    area.scrollTop = area.scrollHeight;
  }

  function appendTyping() {
    const area = document.getElementById("chatArea");
    const div = document.createElement("div");
    div.className = "bubble agent typing";
    div.id = "typingIndicator";
    div.textContent = "Marina está digitando...";
    area.appendChild(div);
    area.scrollTop = area.scrollHeight;
  }

  function removeTyping() {
    const el = document.getElementById("typingIndicator");
    if (el) el.remove();
  }

  function updateStatus(data) {
    const bar = document.getElementById("statusBar");
    const tagHtml = Object.entries(data.tags || {})
      .map(([k, v]) => `<span class="tag-pill">${k}: ${v}</span>`)
      .join(" ");
    bar.innerHTML =
      `Node: <b>${data.node}</b> &nbsp;|&nbsp; ` +
      `Intenção: <b>${data.intent || "—"}</b> &nbsp;|&nbsp; ` +
      `Aguardando: <b>${data.awaiting ? "Sim" : "Não"}</b>` +
      (tagHtml ? `<br/>${tagHtml}` : "");
    document.getElementById("headerStatus").textContent =
      data.awaiting ? "Aguardando resposta do lead..." : "Agente processando...";
  }

  async function sendMessage() {
    const textarea = document.getElementById("msgInput");
    const btn = document.getElementById("sendBtn");
    const msg = textarea.value.trim();
    if (!msg) return;

    textarea.value = "";
    textarea.style.height = "auto";
    btn.disabled = true;

    appendBubble(msg, "user", now());
    appendTyping();

    try {
      const resp = await fetch(`${API}/test/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: getPhone(), message: msg }),
      });

      if (!resp.ok) {
        const err = await resp.text();
        removeTyping();
        appendBubble(`[ERRO ${resp.status}] ${err}`, "agent", now());
        return;
      }

      const data = await resp.json();
      removeTyping();

      if (data.messages && data.messages.length > 0) {
        for (const m of data.messages) {
          appendBubble(m, "agent", now());
        }
      } else {
        appendBubble("(agente não enviou mensagem nesta rodada)", "agent", now());
      }

      updateStatus(data);
    } catch (e) {
      removeTyping();
      appendBubble(`[ERRO de rede] ${e.message}`, "agent", now());
    } finally {
      btn.disabled = false;
      textarea.focus();
    }
  }

  async function resetConversation() {
    const phone = getPhone();
    if (!confirm(`Resetar conversa do número ${phone}?`)) return;

    const resp = await fetch(`${API}/test/chat/${encodeURIComponent(phone)}`, { method: "DELETE" });
    const data = await resp.json();

    document.getElementById("chatArea").innerHTML = "";
    document.getElementById("statusBar").textContent = "Conversa resetada.";
    document.getElementById("headerStatus").textContent = "Agente de IA · Modo Teste";

    appendBubble(
      data.reset
        ? `✅ Conversa resetada para ${phone}. Envie uma nova mensagem para começar.`
        : `ℹ️ Nenhum lead encontrado para ${phone}. Pronto para nova conversa.`,
      "agent",
      now()
    );
  }

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
    // Auto-resize
    const ta = document.getElementById("msgInput");
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
  }
</script>
</body>
</html>"""


@router.get("/ui", response_class=HTMLResponse)
async def test_ui():
    """Interface HTML para testar a conversação com o agente."""
    return HTMLResponse(content=_HTML)
