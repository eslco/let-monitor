from flask import Flask, request, jsonify, render_template
from core import ForumMonitor
import json
import threading
from dotenv import load_dotenv
import os
from functools import wraps

load_dotenv('data/.env')
expected_token = os.getenv('ACCESS_TOKEN', 'default_token')

app = Flask(__name__)
monitor = ForumMonitor()

# 避免冲突
app.jinja_env.variable_start_string = '<<'
app.jinja_env.variable_end_string = '>>'

# 认证装饰器
def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or token != f"Bearer {expected_token}":
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET', 'POST'])
@require_auth
def config():
    if request.method == 'POST':
        data = request.json
        with open('data/config.json', 'w') as f:
            json.dump(data, f, indent=4)
        monitor.reload()
        return jsonify({"status": "success", "message": "Config updated"})
    else:
        return jsonify(monitor.config)


if __name__ == '__main__':
    thread = threading.Thread(target=monitor.start_monitoring)
    thread.daemon = True  # 设置为后台线程，这样主线程退出时它会自动退出
    thread.start()
    app.run(debug=True,host='0.0.0.0',port=5556)
