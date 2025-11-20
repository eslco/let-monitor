import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from send import NotificationSender
import os
from pymongo import MongoClient
import cfscrape
import shutil
from dotenv import load_dotenv
from urllib.parse import urlparse
from msgparse import thread_message, comment_message
# Load variables from data/.env
load_dotenv('data/.env')


scraper = cfscrape.create_scraper()


class ForumMonitor:
    def __init__(self, config_path='data/config.json'):
        self.config_path = config_path
        self.mongo_host = os.getenv("MONGO_HOST", 'mongodb://localhost:27017/')
        self.load_config()

        self.mongo_client = MongoClient(self.mongo_host)
        self.db = self.mongo_client['forum_monitor']
        self.threads = self.db['threads']
        self.comments = self.db['comments']

        self.threads.create_index('link', unique=True)
        self.comments.create_index('comment_id', unique=True)

    # 简化版当前时间调用函数
    def current_time(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # 简化配置加载
    def load_config(self):
        # 如果配置文件不存在，复制示例文件
        if not os.path.exists(self.config_path):
            shutil.copy('example.json', self.config_path)
        with open(self.config_path, 'r') as f:
            self.config = json.load(f)['config']
        self.notifier = NotificationSender(self.config_path)
        print("配置文件加载成功")

    def keywords_filter(self, text):
        keywords_rule = self.config.get('keywords_rule', '')
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
        inputs = [
            { "role": "system", "content": prompt},
            { "role": "user", "content": description}
        ]
        output = self.workers_ai_run(self.config['model'], inputs) # "@cf/qwen/qwen1.5-14b-chat-awq"
        # print(output)
        return output['result']['response'].split('END')[0]


    # -------- RSS LET/LES -----------
    def check_lets(self, urls):
        for url in urls:
            domain = url.split("//")[1].split(".")[0]
            category = url.split("/")[4]
            # 当前时间
            print(f"[{self.current_time()}] 检查 {domain} {category} RSS...")
            res = scraper.get(url)
            if res.status_code != 200:
                print(f"获取 {domain} 失败")
                return
            soup = BeautifulSoup(res.text, 'xml')
            for item in soup.find_all('item')[:3]:
                self.convert_rss(item, domain, category)

    # 将 RSS item 转成 thread_data
    def convert_rss(self, item, domain, category):
        title = item.find('title').text
        link = item.find('link').text
        desc = BeautifulSoup(item.find('description').text, 'lxml').text
        creator = item.find('dc:creator').text
        pub_date = datetime.strptime(item.find('pubDate').text, "%a, %d %b %Y %H:%M:%S +0000")

        thread_data = {
            'domain': domain,
            'category': category,
            'title': title,
            'link': link,
            'description': desc,
            'creator': creator,
            'pub_date': pub_date,
            'created_at': datetime.now(timezone.utc),
            'last_page': 1
        }

        self.handle_thread(thread_data)
        self.fetch_comments(thread_data)

    # -------- 线程存储 + 通知 --------
    def handle_thread(self, thread):
        exists = self.threads.find_one({'link': thread['link']})
        if exists:
            return

        self.threads.insert_one(thread)
        # 发布时间 24h 内才推送
        if (datetime.now(timezone.utc) - thread['pub_date'].replace(tzinfo=timezone.utc)).total_seconds() <= 86400:
            if self.config.get('use_keywords_filter', False) and (not self.keywords_filter(thread['description'])):
                    return
            if self.config.get('use_ai_filter', False):
                ai_description = self.ai_filter(thread['description'],self.config['thread_prompt'])
                if ai_description == "FALSE":
                    return
            else:
                ai_description = ""
            msg = thread_message(thread, ai_description)
            self.notifier.send_message(msg)

    # 新增：直接抓取单个线程页面并解析成 thread_data 格式
    def fetch_thread_page(self, url):
        res = scraper.get(url)
        if res.status_code != 200:
            print(f"获取页面失败 {url} 状态码 {res.status_code}")
            return None

        soup = BeautifulSoup(res.text, "html.parser")

        item_header = soup.select_one("div.Item-Header.DiscussionHeader")
        page_title = soup.select_one("#Item_0.PageTitle")

        if not item_header or not page_title:
            print("结构不匹配")
            return None

        title = page_title.select_one("h1")
        title = title.text.strip() if title else ""

        creator = item_header.select_one(".Author .Username")
        creator = creator.text.strip() if creator else ""

        time_el = item_header.select_one("time")
        if time_el and time_el.has_attr("datetime"):
            pub_date_str = time_el["datetime"]
            try:
                pub_date = datetime.strptime(pub_date_str, "%Y-%m-%dT%H:%M:%S+00:00")
            except ValueError:
                pub_date = datetime.now(timezone.utc)  # 如果解析失败，使用当前时间
        else:
            pub_date = datetime.now(timezone.utc)

        category = item_header.select_one(".Category a")
        category = category.text.strip() if category else ""

        desc_el = soup.select_one(".Message.userContent")
        description = desc_el.get_text("\n", strip=True) if desc_el else ""

        parsed = urlparse(url)
        domain = parsed.netloc

        thread_data = {
            "domain": domain,
            "category": category,
            "title": title,
            "link": url,
            "description": description,
            "creator": creator,
            "pub_date": pub_date,
            "created_at": datetime.now(timezone.utc),
            "last_page": 1
        }

        self.handle_thread(thread_data)
        self.fetch_comments(thread_data)


    # -------- 评论抓取统一逻辑（LET / LES 一样） --------
    def fetch_comments(self, thread):
        last_page = self.threads.find_one({'link': thread['link']}).get('last_page', 1)

        while True:
            page_url = f"{thread['link']}/p{last_page}"
            res = scraper.get(page_url)

            if res.status_code != 200:
                # 更新 last_page
                self.threads.update_one(
                    {'link': thread['link']},
                    {'$set': {'last_page': last_page - 1}}
                )
                break

            self.parse_comments(res.text, thread)
            last_page += 1
            time.sleep(1)

    # -------- 通用评论解析 --------
    def parse_comments(self, html, thread):
        soup = BeautifulSoup(html, 'html.parser')
        items = soup.find_all('li', class_='ItemComment')

        for it in items:
            cid = it.get('id')
            if not cid:
                continue
            cid = cid.split('_')[1]

            author = it.find('a', class_='Username').text
            role = it.find('span', class_='RoleTitle').text if it.find('span', class_='RoleTitle') else None
            msg = it.find('div', class_='Message').text.strip()
            created = it.find('time')['datetime']

            if self.config.get('comment_filter') == 'by_role':
                # by_role 过滤器，为 None '' 或者只有 member 则跳过
                if not role or role.strip().lower() == 'member':
                    continue
            if self.config.get('comment_filter') == 'by_author':
                # 只监控作者自己的后续更新
                if author != thread['creator']:
                    continue

            comment = {
                'comment_id': f"{thread['domain']}_{cid}",
                'thread_url': thread['link'],
                'author': author,
                'message': msg[:200].strip(),
                'created_at': datetime.strptime(created, "%Y-%m-%dT%H:%M:%S+00:00"),
                'created_at_recorded': datetime.now(timezone.utc),
                'url': f"{thread['link']}/comment/{cid}/#Comment_{cid}"
            }

            self.handle_comment(comment, thread)

    # -------- 存储评论 + 通知 --------
    def handle_comment(self, comment, thread):
        if self.comments.find_one({'comment_id': comment['comment_id']}):
            return

        self.comments.update_one({'comment_id': comment['comment_id']},
                                 {'$set': comment}, upsert=True)

        # 只推送 24 小时内的
        if (datetime.now(timezone.utc) - comment['created_at'].replace(tzinfo=timezone.utc)).total_seconds() <= 86400:
            if self.config.get('use_keywords_filter', False) and (not self.keywords_filter(comment['message'])):
                    return
            if self.config.get('use_ai_filter', False):
                ai_description = self.ai_filter(comment['message'],self.config['comment_prompt'])
                if ai_description == "FALSE":
                    return
            else:
                ai_description = ""
            msg = comment_message(thread, comment, ai_description)
            self.notifier.send_message(msg)

    # -------- 主循环 --------
    def start_monitoring(self):
        print("开始监控...")
        freq = self.config.get('frequency', 600)

        while True:
            self.check_lets(urls=self.config.get('urls', [
                "https://lowendspirit.com/categories/offers/feed.rss",
                "https://lowendtalk.com/categories/offers/feed.rss"
            ]))
            time.sleep(freq)

    # 外部重载配置方法
    def reload(self):
        print("重新加载配置...")
        self.load_config()
        
if __name__ == "__main__":
    monitor = ForumMonitor()
    monitor.start_monitoring()
