import requests
import json

class NotificationSender:
    def __init__(self, config):
        self.config = config

    # 发送 Telegram 消息
    def send_telegram_message(self, message):
        telegram_token = self.config.get('telegrambot')
        chat_id = self.config.get('chat_id')
        if telegram_token and chat_id:
            url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message
            }
            try:
                response = requests.get(url, params=payload)
                if response.status_code == 200:
                    print("Telegram 消息发送成功")
                else:
                    print(f"Telegram 消息发送失败: {response.status_code}")
            except Exception as e:
                print(f"发送 Telegram 消息出错: {e}")
        else:
            print("Telegram 配置缺失：请检查 token 或 chat_id")

    # 发送微信消息
    def send_wechat_message(self, message):
        wechat_key = self.config.get('wechat_key')
        if wechat_key:
            url = f"https://xizhi.qqoq.net/{wechat_key}.send"
            payload = {
                'title': '库存变更通知',
                'content': message
            }
            try:
                response = requests.get(url, params=payload)
                if response.status_code == 200:
                    print("微信消息发送成功")
                else:
                    print(f"微信消息发送失败: {response.status_code}")
            except Exception as e:
                print(f"发送微信消息出错: {e}")
        else:
            print("微信推送密钥未配置：请检查 wechat_key 配置")

    # 发送自定义通知
    def send_custom_message(self, message):
        custom_url = self.config.get('custom_url')
        if custom_url:
            custom_url_with_message = custom_url.replace("{message}", message)
            try:
                response = requests.get(custom_url_with_message)
                if response.status_code == 200:
                    print(f"自定义通知发送成功: {message}")
                else:
                    print(f"自定义通知发送失败: {response.status_code}")
            except Exception as e:
                print(f"发送自定义通知出错: {e}")
        else:
            print("自定义 URL 配置缺失：请检查 custom_url 配置")

    # 发送通知
    def send_message(self, message):
        print(message)
        # return None
        notice_type = self.config.get('notice_type', 'telegram')
        
        if notice_type == 'telegram':
            self.send_telegram_message(message)
        elif notice_type == 'wechat':
            self.send_wechat_message(message)
        elif notice_type == 'custom':
            self.send_custom_message(message)
        else:
            print("不支持的通知类型:", notice_type)

# 示例调用
if __name__ == "__main__":
    sender = NotificationSender(config_path='data/config.json')
    sender.send_message("测试消息：这是一个通知")
