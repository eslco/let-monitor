import json
import requests
import os
import shutil

class Filter:
    def __init__(self, config):
        self.config = config

    def keywords_filter(self, text, keywords_rule):
        if not keywords_rule.strip():
            return False
        or_groups = [group.strip() for group in keywords_rule.split(',')]
        for group in or_groups:
            # Split by + for AND keywords
            and_keywords = [kw.strip() for kw in group.split('+')]
            # Check if all AND keywords are in the text (case-insensitive)
            if all(kw.lower() in text.lower() for kw in and_keywords):
                return True
        return False

    # -------- AI 相关功能 --------
    def workers_ai_run(self, model, inputs):
        headers = {"Authorization": f"Bearer {self.config['cf_token']}"}
        input = { "messages": inputs }
        response = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{self.config['cf_account_id']}/ai/run/{model}", headers=headers, json=input)
        return response.json()

    def ai_filter(self, description, prompt):
        print('Using AI')
        inputs = [
            { "role": "system", "content": prompt},
            { "role": "user", "content": description}
        ]
        output = self.workers_ai_run(self.config['model'], inputs) # "@cf/qwen/qwen1.5-14b-chat-awq"
        print(output)
        # return output['result']['response'].split('END')[0]
        return output['result']['choices'][0]['message']['content'].split('END')[0]