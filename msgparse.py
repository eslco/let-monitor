
def thread_message(thread, ai_description):
    msg = (
        f"{thread['domain'].upper()} 新促销\n"
        f"标题：{thread['title']}\n"
        f"作者：{thread['creator']}\n"
        f"时间：{thread['pub_date'].strftime('%Y/%m/%d %H:%M')}\n\n"
        + (
            f"{ai_description[:200].strip()}"
            + ("..." if len(ai_description) > 200 else "")
            + "\n\n"
            if ai_description else ""
        )
        + f"{thread['link']}"
    )
    return msg

def comment_message(thread, comment, ai_description):
    msg = (
        f"{thread['domain'].upper()} 新评论\n"
        f"作者：{comment['author']}\n"
        f"时间：{comment['created_at'].strftime('%Y/%m/%d %H:%M')}\n\n"
        f"{comment['message'][:200].strip()}...\n\n"
        + (
            f"{ai_description[:200].strip()}"
            + ("..." if len(ai_description) > 200 else "")
            + "\n\n"
            if ai_description else ""
        )
        + f"{comment['url']}"
    )
    return msg

