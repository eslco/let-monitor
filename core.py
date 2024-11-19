import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from send import NotificationSender
import os
from pymongo import MongoClient
import cfscrape

scraper = cfscrape.create_scraper()  # returns a CloudflareScraper instance




class ForumMonitor:
    def __init__(self, config_path='data/config.json'):
        self.config_path = config_path
        self.proxy_host = os.getenv("PROXY_HOST", None)  # 从环境变量读取代理配置
        self.mongo_host = os.getenv("MONGO_HOST", 'mongodb://localhost:27017/')  # 从环境变量读取代理配置
        self.load_config()

        # 连接到 MongoDB
        self.mongo_client = MongoClient(self.mongo_host)  # 默认连接到本地 MongoDB
        self.db = self.mongo_client['forum_monitor']  # 使用数据库 'forum_monitor'
        self.threads_collection = self.db['threads']  # 线程集合
        self.comments_collection = self.db['comments']  # 评论集合

    # 加载配置文件
    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)['config']
                self.notifier = NotificationSender(self.config_path)  # 创建通知发送器
            print("配置文件加载成功")
        except Exception as e:
            print(f"加载配置失败: {e}")
            self.config = {}

    def workers_ai_run(self, model, inputs):
        headers = {"Authorization": f"Bearer {self.config['cf_token']}"}
        input = { "messages": inputs }
        response = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{self.config['cf_account_id']}/ai/run/{model}", headers=headers, json=input)
        return response.json()

    # 用AI总结Thread
    def get_summarize_from_ai(self, description):
        inputs = [
            { "role": "system", "content": self.config['thread_prompt'] }, # "你是一个中文智能助手，帮助我筛选一个 VPS (Virtual Private Server, 虚拟服务器) 交流论坛的信息。接下来我要给你一条信息，请你用50字简短总结，并用100字介绍其提供的价格最低的套餐（介绍其价格、配置以及对应的优惠码，如果有）。格式为：摘要：xxx\n优惠套餐：xxx"
            { "role": "user", "content": description}
        ]

        output = self.workers_ai_run(self.config['model'], inputs) # "@cf/qwen/qwen1.5-14b-chat-awq"
        # print(output)
        return output['result']['response']

    # 用AI判断评论是否值得推送
    def get_filter_from_ai(self, description):
        inputs = [
            { "role": "system", "content": self.config['filter_prompt'] }, # "你是一个中文智能助手，帮助我筛选一个 VPS (Virtual Private Server, 虚拟服务器) 交流论坛的信息。接下来我要给你一条信息，如果满足筛选规则，请你返回文段翻译，如果文段超过100字，翻译后再进行摘要，如果不满足，则返回 "FALSE"。 筛选条件：这条评论需要提供了一个新的优惠活动 discount，或是发起了一组抽奖 giveaway，或是提供了优惠码 code，或是补充了供货 restock，除此之外均返回FALSE。返回格式：内容：XXX 或者 FALSE。"
            { "role": "user", "content": description}
        ]

        output = self.workers_ai_run(self.config['model'], inputs) # "@cf/qwen/qwen1.5-14b-chat-awq"
        # print(output)
        return output['result']['response']

    # 检查 RSS
    def check_rss(self, url):
        print(f"正在检查 RSS: {url}")
        try:
            response = scraper.get(url)
            if response.status_code == 200:
                rss_feed = response.text
                self.parse_rss(rss_feed)
            else:
                print(f"无法获取 RSS 数据: {response.status_code}")
        except Exception as e:
            print(f"获取 RSS 出错: {e}")

    # 解析 RSS 内容
    def parse_rss(self, rss_feed):
        soup = BeautifulSoup(rss_feed, 'xml')
        items = soup.find_all('item')
        # 只看前 10 个
        for item in items[:10]:
            # print(item)
            title = item.find('title').text
            link = item.find('link').text
            description = item.find('description').text
            pub_date = item.find('pubDate').text
            creator = item.find('dc:creator').text
            # 检查是否已经有该线程
            existing_thread = self.threads_collection.find_one({'link': link})

            if not existing_thread:
                # 存储 RSS 线程到 MongoDB
                thread_data = {
                    'title': title,
                    'link': link,
                    'description': description,
                    'pub_date': pub_date,
                    'created_at': datetime.utcnow(),
                    'creator': creator,
                    'last_page': 1  # 默认从第一页开始抓取
                }
                self.threads_collection.insert_one(thread_data)  # 仅当线程不存在时插入

                print(f"线程已存储: {title}, 链接: {link}")
 
                # 解析 pub_date 为 datetime 对象
                pub_datetime = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S +0000")
                current_time = datetime.utcnow()
                time_diff = current_time - pub_datetime

                # 如果文章发布时间在当前时间的一天内，则发送通知
                if time_diff.total_seconds() <= 24 * 60 * 60:  # 24小时以内
                    # 格式化发布时间为所需格式
                    formatted_pub_date = pub_datetime.strftime("%Y/%m/%d %H:%M")
                    
                    # 生成文章概要
                    summary = self.get_summarize_from_ai(description)
                    
                    # 创建消息内容
                    message = (
                        f"标题：{title}\n"
                        f"作者：{creator}\n"  # 如果有作者信息，可替换 '未知' 为实际值
                        f"发布时间：{formatted_pub_date}\n"
                        f"{summary}\n"
                        f"链接：{link}"
                    )

                    self.notifier.send_message(message)
            else:
                # print(f"线程已存在: {link}")
                pass

            # 开始抓取这个线程的所有页面
            self.check_page(link)

    # 获取页面信息
    def check_page(self, thread_url):
        # print(f"正在线程页面: {thread_url}")
        try:
            # 获取当前线程的最后一页数据
            thread_info = self.threads_collection.find_one({'link': thread_url})
            if thread_info:
                last_page = thread_info.get('last_page', 1)
                # print(f"上次抓取的页面是: {last_page}")
                # 根据当前最后一页抓取接下来的页面
                self.fetch_all_pages(thread_url, last_page, thread_info)
            else:
                print(f"未找到该线程信息: {thread_url}")
        except Exception as e:
            print(f"获取页面出错: {e}")

    # 获取线程所有页面的评论
    def fetch_all_pages(self, thread_url, last_page, thread_info):
        # 以某种方式获取所有分页的 URL
        while True:
            page_url = f"{thread_url}/p{last_page}"  # 拼接分页 URL
            response = scraper.get(page_url)
            if response.status_code == 200:
                # print(f"抓取页面: {page_url} 成功")
                page_content = response.text
                self.parse_page(page_content, page_url, thread_info)
                last_page += 1
                time.sleep(2)  # 可以适当延时防止过于频繁的请求
            else:
                # print(f"已获取到最终一页, 共 {last_page-1} 页")
                # 更新 MongoDB 中该线程的 last_page
                self.threads_collection.update_one(
                    {'link': thread_url},
                    {'$set': {'last_page': last_page-1}}
                )
                break  # 如果没有更多页面，则停止抓取
            
    # 解析页面信息
    def parse_page(self, page_content, url, thread_info):
        soup = BeautifulSoup(page_content, 'html.parser')
        # 获取所有评论
        comments = soup.find_all('li', class_='ItemComment')
        for comment in comments:
            # 通过 ID 获取评论唯一标识
            comment_id = comment.get('id')
            if not comment_id:
                continue  # 如果没有 id，则跳过此评论
            
            comment_id = comment_id.split('_')[1]  # 提取 id 中的数字部分

            # 提取评论中的数据
            author = comment.find('a', class_='Username').text
            message = comment.find('div', class_='Message').text.strip()
            created_at = comment.find('time')['datetime']
            author_url = comment.find('a', class_='Username')['href']
            
            existing_comment = self.comments_collection.find_one({'comment_id': comment_id})

            if not existing_comment:
                comment_data = {
                    'comment_id': comment_id,  # 使用 comment_id 作为唯一标识符
                    'thread_url': url,
                    'author': author,
                    # 'message': message,
                    # 优化存储
                    'message': message[:200],
                    'created_at': datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S+00:00"),
                    'author_url': author_url,
                    'created_at_recorded': datetime.utcnow()
                }

                # 存储评论到 MongoDB，使用 comment_id 确保唯一性
                self.comments_collection.update_one(
                    {'comment_id': comment_id},  # 使用 comment_id 作为唯一标识符
                    {'$set': comment_data},
                    upsert=True  # 如果该评论不存在则插入，否则更新
                )
                # print(f"评论已存储: 作者: {author}, 内容: {message[:30]}...")
                
                # 根据关键字发送通知
                # keyword = self.config.get('config', {}).get('keyword', '')
                # if keyword.lower() in message.lower():
                #     self.notifier.send_message(f"新评论匹配关键字 '{keyword}':\n{message}")
    
                created_datetime = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S+00:00")
                current_time = datetime.utcnow()
                time_diff = current_time - created_datetime
                # 如果文章发布时间在当前时间的一天内，则发送通知
                if time_diff.total_seconds() <= 24 * 60 * 60 and author == thread_info['creator']:  # 24小时以内
                    ai_response = self.get_filter_from_ai(message)
                    if not  "FALSE" in ai_response:
                        # 格式化发布时间为所需格式
                        formatted_pub_date = created_datetime.strftime("%Y/%m/%d %H:%M")

                        # 创建消息内容
                        message_ = (
                            f"作者：{author}\n"  # 如果有作者信息，可替换 '未知' 为实际值
                            f"发布时间：{formatted_pub_date}\n"
                            f"{ai_response}\n"
                            f"链接：https://lowendtalk.com/discussion/comment/{comment_id}/#Comment_{comment_id}"
                        )

                        self.notifier.send_message(message_)
                    else:
                        print(f'AI skip {message}')
                    # if  and not 'thank you' in message.lower():
                    #     self.notifier.send_message(f"商家新评论 '{author}':\n{message[:200]}....\n")
    
    # 监控主循环
    def start_monitoring(self):
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 开始监控...")
        # rss_url = self.config.get('rss_url')
        rss_url = "https://lowendtalk.com/categories/offers/feed.rss"
        frequency = self.config.get('frequency', 600)  # 默认每10分钟检测一次
        
        while True:
            try:
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 开始遍历...")
                self.check_rss(rss_url)  # 检查 RSS
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 遍历完成...")
            except Exception as e:
                print(f"检测过程出现错误: {e}")
            time.sleep(frequency)

    # 外部重载配置方法
    def reload(self):
        print("重新加载配置...")
        self.load_config()

# 示例运行
if __name__ == "__main__":
    monitor = ForumMonitor(config_path='data/config.json')
    monitor.start_monitoring()