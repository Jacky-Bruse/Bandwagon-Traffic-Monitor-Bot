import os
import requests
import datetime
import logging
from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, CallbackContext

# 启用日志记录
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# 从环境变量获取配置
BWH_VEID = os.environ.get("BWH_VEID")
BWH_API_KEY = os.environ.get("BWH_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
# 将 Chat ID 作为授权用户列表，用逗号分隔
AUTHORIZED_USERS = [int(user_id.strip()) for user_id in os.environ.get("TELEGRAM_CHAT_ID", "").split(',') if user_id.strip()]

def get_bwh_service_info():
    """通过搬瓦工 API 获取 VPS 服务信息"""
    if not BWH_VEID or not BWH_API_KEY:
        logger.error("BWH_VEID 或 BWH_API_KEY 未设置。")
        return None, "搬瓦工 API 凭证未在环境中设置。"

    url = f"https://api.64clouds.com/v1/getServiceInfo?veid={BWH_VEID}&api_key={BWH_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get("error") != 0:
            return None, data.get('message', 'API 返回未知错误')
        return data, None
    except requests.exceptions.RequestException as e:
        logger.error(f"请求搬瓦工 API 时发生错误: {e}")
        return None, f"请求搬瓦工 API 时发生网络错误: {e}"

def format_bytes(byte_count):
    """将字节数格式化为 GB"""
    if byte_count is None:
        return 0
    return round(byte_count / (1024**3), 2)

def start(update: Update, context: CallbackContext) -> None:
    """响应 /start 命令"""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        update.message.reply_text("抱歉，您无权使用此机器人。")
        return

    update.message.reply_markdown_v2(
        fr'你好，{user.mention_markdown_v2()}\! '
        fr'使用 /traffic 命令来查询搬瓦工 VPS 的实时流量信息。'
    )

def get_traffic_info(update: Update, context: CallbackContext) -> None:
    """响应 /traffic 命令，查询并发送流量信息"""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        update.message.reply_text("抱歉，您无权使用此机器人。")
        return
    
    update.message.reply_text("正在查询流量信息，请稍候...")

    info, error_message = get_bwh_service_info()

    if error_message:
        update.message.reply_text(f"查询失败: {error_message}")
        return

    if info:
        plan_monthly_data = info.get("plan_monthly_data")
        data_counter = info.get("data_counter")
        data_next_reset = datetime.datetime.fromtimestamp(info.get("data_next_reset")).strftime('%Y-%m-%d')
        
        used_gb = format_bytes(data_counter)
        total_gb = format_bytes(plan_monthly_data)
        
        usage_percent = round((data_counter / plan_monthly_data) * 100, 2) if plan_monthly_data > 0 else 0

        message = (
            f"**搬瓦工 VPS 流量报告**\n\n"
            f"主机名: `{info.get('hostname')}`\n"
            f"套餐: `{info.get('plan')}`\n\n"
            f"已用流量: `{used_gb} GB`\n"
            f"总流量: `{total_gb} GB`\n"
            f"使用率: `{usage_percent}%`\n\n"
            f"流量重置日期: `{data_next_reset}`"
        )
        update.message.reply_text(message, parse_mode='Markdown')
    else:
        update.message.reply_text("无法获取 VPS 信息。")

def main() -> None:
    """启动机器人"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN 未在环境中设置。")
        exit(1)
    if not AUTHORIZED_USERS:
        logger.warning("TELEGRAM_CHAT_ID 未设置，机器人将对所有用户开放。")

    # 使用新的 Builder 模式创建 Updater
    updater = Updater.builder().token(TELEGRAM_BOT_TOKEN).build()

    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("traffic", get_traffic_info))

    updater.start_polling()
    logger.info("机器人已启动。")
    updater.idle()

if __name__ == '__main__':
    main() 