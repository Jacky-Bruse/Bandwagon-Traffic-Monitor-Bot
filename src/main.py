import os
import requests
import datetime
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# 启用日志记录
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# 从环境变量获取配置
BWH_API_KEY = os.environ.get("BWH_API_KEY")
# 将 VEID 作为列表读取
BWH_VEIDS = [veid.strip() for veid in os.environ.get("BWH_VEID", "").split(',') if veid.strip()]
# 将 Chat ID 作为授权用户列表，用逗号分隔
AUTHORIZED_USERS = [int(user_id.strip()) for user_id in os.environ.get("TELEGRAM_CHAT_ID", "").split(',') if user_id.strip()]

def get_bwh_service_info(veid, api_key):
    """通过搬瓦工 API 获取指定 VEID 的 VPS 服务信息"""
    if not veid or not api_key:
        logger.error("BWH_VEID 或 BWH_API_KEY 未提供。")
        return None, "搬瓦工 API 凭证未在环境中设置。"

    url = f"https://api.64clouds.com/v1/getServiceInfo?veid={veid}&api_key={api_key}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get("error") != 0:
            return None, data.get('message', 'API 返回未知错误')
        return data, None
    except requests.exceptions.RequestException as e:
        logger.error(f"请求搬瓦工 API 时发生错误 (VEID: {veid}): {e}")
        return None, f"请求搬瓦工 API 时发生网络错误"

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

    update.message.reply_markdown(
        f'你好，{user.mention_markdown()}! '
        f'使用 /traffic 命令来查询所有已配置的搬瓦工 VPS 的实时流量信息。'
    )

def get_traffic_info(update: Update, context: CallbackContext) -> None:
    """响应 /traffic 命令，查询并发送所有 VPS 的流量信息"""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        update.message.reply_text("抱歉，您无权使用此机器人。")
        return

    if not BWH_VEIDS:
        update.message.reply_text("错误: `BWH_VEID` 环境变量未设置或为空。请确保已配置一个或多个 VEID。")
        return

    update.message.reply_text("正在查询所有 VPS 的流量信息，请稍候...")

    report_parts = ["*搬瓦工 VPS 流量总报告*"]

    for veid in BWH_VEIDS:
        info, error_message = get_bwh_service_info(veid, BWH_API_KEY)

        if error_message:
            report_parts.append(f"\n------\n*VPS (VEID: `{veid}`)*\n查询失败: `{error_message}`")
            continue
        
        if info:
            plan_monthly_data = info.get("plan_monthly_data")
            data_counter = info.get("data_counter")
            data_next_reset = datetime.datetime.fromtimestamp(info.get("data_next_reset")).strftime('%Y-%m-%d')
            
            used_gb = format_bytes(data_counter)
            total_gb = format_bytes(plan_monthly_data)
            
            usage_percent = round((data_counter / plan_monthly_data) * 100, 2) if plan_monthly_data > 0 else 0

            part = (
                f"\n------\n"
                f"*主机:* `{info.get('hostname')}`\n"
                f"*套餐:* `{info.get('plan')}`\n"
                f"已用流量: `{used_gb} GB` / `{total_gb} GB`\n"
                f"使用率: `{usage_percent}%`\n"
                f"流量重置日期: `{data_next_reset}`"
            )
            report_parts.append(part)

    final_report = "\n".join(report_parts)
    update.message.reply_text(final_report, parse_mode='Markdown')

def main() -> None:
    """启动机器人"""
    if not BWH_API_KEY or not TELEGRAM_BOT_TOKEN or not AUTHORIZED_USERS:
        logger.error("错误: 缺少必要的环境变量。请检查 BWH_API_KEY, TELEGRAM_BOT_TOKEN, 和 TELEGRAM_CHAT_ID。")
        exit(1)

    # 使用 v13.x 的方式初始化 Updater
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)

    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("traffic", get_traffic_info))

    updater.start_polling()
    logger.info("机器人已启动，支持多 VPS 查询。")
    updater.idle()

if __name__ == '__main__':
    main() 