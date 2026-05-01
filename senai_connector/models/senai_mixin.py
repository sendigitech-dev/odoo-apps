import json
import urllib.request
import urllib.error
from odoo import models
from odoo.exceptions import UserError

_GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'
_GEMINI_FALLBACKS = ['gemini-2.0-flash', 'gemini-2.5-flash-lite']


class SenaiMixin(models.AbstractModel):
    _name = 'senai.mixin'
    _description = 'Mixin SenAI'

    def action_ask_senai(self, prompt, system_prompt=None):
        """Envoie un message à l'IA configurée et retourne la réponse texte."""
        config = self.env['senai.config'].get_config()
        messages = [{'role': 'user', 'content': prompt}]

        if config.provider == 'openai':
            return self._senai_call_openai(config, messages, system_prompt)
        elif config.provider == 'anthropic':
            return self._senai_call_anthropic(config, messages, system_prompt)
        else:
            return self._senai_call_gemini(config, messages, system_prompt)

    def _senai_call_gemini(self, config, messages, system_prompt):
        history = [
            {
                'role': 'user' if m['role'] == 'user' else 'model',
                'parts': [{'text': m['content']}],
            }
            for m in messages
        ]
        payload = {'contents': history}
        if system_prompt:
            payload['systemInstruction'] = {'parts': [{'text': system_prompt}]}

        models_to_try = [config.model_id] + [
            m for m in _GEMINI_FALLBACKS if m != config.model_id
        ]
        for model in models_to_try:
            url = f'{_GEMINI_BASE}/{model}:generateContent?key={config.api_key}'
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    return result['candidates'][0]['content']['parts'][0]['text']
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8')
                if e.code in (429, 503) and model != models_to_try[-1]:
                    continue
                raise UserError(self._senai_friendly_error('Gemini', e.code, body))
            except urllib.error.URLError:
                raise UserError("Impossible de joindre l'API Gemini. Vérifiez votre connexion.")

    def _senai_call_openai(self, config, messages, system_prompt):
        oai_messages = []
        if system_prompt:
            oai_messages.append({'role': 'system', 'content': system_prompt})
        oai_messages += [{'role': m['role'], 'content': m['content']} for m in messages]

        payload = {
            'model': config.model_id or 'gpt-4o',
            'messages': oai_messages,
            'max_tokens': 4096,
        }
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {config.api_key}',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result['choices'][0]['message']['content']
        except urllib.error.HTTPError as e:
            raise UserError(self._senai_friendly_error('OpenAI', e.code, e.read().decode('utf-8')))
        except urllib.error.URLError:
            raise UserError("Impossible de joindre l'API OpenAI. Vérifiez votre connexion.")

    def _senai_call_anthropic(self, config, messages, system_prompt):
        payload = {
            'model': config.model_id or 'claude-opus-4-7',
            'max_tokens': 4096,
            'messages': [{'role': m['role'], 'content': m['content']} for m in messages],
        }
        if system_prompt:
            payload['system'] = system_prompt

        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'x-api-key': config.api_key,
                'anthropic-version': '2023-06-01',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result['content'][0]['text']
        except urllib.error.HTTPError as e:
            raise UserError(self._senai_friendly_error('Anthropic', e.code, e.read().decode('utf-8')))
        except urllib.error.URLError:
            raise UserError("Impossible de joindre l'API Anthropic. Vérifiez votre connexion.")

    def _senai_friendly_error(self, provider, code, body):
        generic = {
            401: f"Clé API {provider} invalide. Vérifiez-la dans SenAI > Configuration.",
            403: f"Accès refusé par l'API {provider}. Vérifiez les droits de votre clé.",
            429: f"Quota API {provider} dépassé. Réessayez dans quelques minutes.",
            503: f"Service {provider} temporairement indisponible. Réessayez dans un instant.",
        }
        if code in generic:
            return generic[code]
        try:
            msg = json.loads(body).get('error', {}).get('message', body)
        except Exception:
            msg = body
        return f'Erreur API {provider} ({code}) : {msg}'
