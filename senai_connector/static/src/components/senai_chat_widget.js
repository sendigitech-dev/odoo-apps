import { Component, useState, useRef, useEffect, onMounted, onWillUnmount, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

function markdownToHtml(text) {
    if (!text) return markup('');
    let s = text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // code blocks
    s = s.replace(/```[^\n]*\n?([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
    // inline code
    s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    // bold
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    // italic
    s = s.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
    // headings
    s = s.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    s = s.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    s = s.replace(/^# (.+)$/gm, '<h2>$1</h2>');
    // lists
    s = s.replace(/^[ \t]*[-*] (.+)$/gm, '<li>$1</li>');
    s = s.replace(/^[ \t]*\d+\. (.+)$/gm, '<li>$1</li>');
    // consecutive <li> → wrap in <ul>
    s = s.replace(/(<li>[\s\S]*?<\/li>)(?=\s*<li>|$)/g, (m) => m); // keep as-is for now
    // line breaks
    s = s.replace(/\n/g, '<br>');
    return markup(s);
}

const CONTEXT_MAP = {
    "/odoo/crm":         { model: "crm.lead",        label: "CRM" },
    "/odoo/sales":       { model: "sale.order",       label: "Ventes" },
    "/odoo/accounting":  { model: "account.move",     label: "Comptabilité" },
    "/odoo/inventory":   { model: "stock.picking",    label: "Inventaire" },
    "/odoo/purchase":    { model: "purchase.order",   label: "Achats" },
    "/odoo/project":     { model: "project.task",     label: "Projets" },
    "/odoo/employees":   { model: "hr.employee",      label: "RH" },
    "/odoo/helpdesk":    { model: "helpdesk.ticket",  label: "Helpdesk" },
};

function detectContext() {
    const path = window.location.pathname;
    for (const [prefix, ctx] of Object.entries(CONTEXT_MAP)) {
        if (path.startsWith(prefix)) return ctx;
    }
    return null;
}

class SenaiChatWidget extends Component {
    static template = "senai_connector.SenaiChatWidget";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            isOpen: false,
            view: "list",           // "list" | "chat"
            conversations: [],
            activeConvId: null,
            activeConvName: "",
            messages: [],
            input: "",
            isLoading: false,
            context: null,          // { model, label }
            loadingConvs: false,
        });

        this.messagesRef = useRef("messages");

        // Scroll automatique vers le bas à chaque nouveau message
        useEffect(
            () => {
                const el = this.messagesRef.el;
                if (el) el.scrollTop = el.scrollHeight;
            },
            () => [this.state.messages.length, this.state.isLoading]
        );

        // Détection du contexte Odoo à chaque changement d'URL
        this._contextTimer = null;
        onMounted(() => {
            this.state.context = detectContext();
            this._contextTimer = setInterval(() => {
                const ctx = detectContext();
                const cur = this.state.context;
                if (ctx?.model !== cur?.model) {
                    this.state.context = ctx;
                }
            }, 1500);
        });

        onWillUnmount(() => {
            if (this._contextTimer) clearInterval(this._contextTimer);
        });
    }

    // ─── Panneau ────────────────────────────────────────────────────

    async togglePanel() {
        this.state.isOpen = !this.state.isOpen;
        if (this.state.isOpen && this.state.view === "list") {
            await this._loadConversations();
        }
    }

    async _loadConversations() {
        this.state.loadingConvs = true;
        try {
            this.state.conversations = await this.orm.call(
                "senai.conversation", "get_conversations", [], {}
            );
        } finally {
            this.state.loadingConvs = false;
        }
    }

    // ─── Navigation ─────────────────────────────────────────────────

    async openConversation(conv) {
        this.state.activeConvId = conv.id;
        this.state.activeConvName = conv.name;
        this.state.messages = [];
        this.state.view = "chat";
        const msgs = await this.orm.call(
            "senai.conversation", "get_messages", [[conv.id]], {}
        );
        this.state.messages = msgs;
    }

    newConversation() {
        this.state.activeConvId = null;
        this.state.activeConvName = "Nouvelle conversation";
        this.state.messages = [];
        this.state.view = "chat";
    }

    async backToList() {
        this.state.view = "list";
        this.state.activeConvId = null;
        this.state.messages = [];
        await this._loadConversations();
    }

    async deleteConversation(ev, convId) {
        ev.stopPropagation();
        if (!confirm("Supprimer cette conversation ? Cette action est irréversible.")) return;
        await this.orm.call("senai.conversation", "delete_conversation", [[convId]], {});
        await this._loadConversations();
    }

    renderContent(content) {
        return markdownToHtml(content);
    }

    // ─── Envoi de message ────────────────────────────────────────────

    async sendMessage() {
        const prompt = this.state.input.trim();
        if (!prompt || this.state.isLoading) return;

        this.state.messages.push({ role: "user", content: prompt });
        this.state.input = "";
        this.state.isLoading = true;

        try {
            const ctx = this.state.context;
            const result = await this.orm.call(
                "senai.conversation",
                "send_message",
                [],
                {
                    conversation_id: this.state.activeConvId || false,
                    prompt,
                    context_model: ctx?.model || false,
                    context_label: ctx?.label || false,
                }
            );
            this.state.activeConvId = result.conversation_id;
            this.state.activeConvName = result.conversation_name;
            this.state.messages.push({ role: "assistant", content: result.answer });
        } catch (e) {
            this.state.messages.push({
                role: "error",
                content: e.data?.message || e.message || "Erreur inattendue.",
            });
        } finally {
            this.state.isLoading = false;
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }
}

registry.category("main_components").add("SenaiChatWidget", {
    Component: SenaiChatWidget,
});
