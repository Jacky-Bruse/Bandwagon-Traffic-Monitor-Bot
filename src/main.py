import os
import requests
import datetime
import logging
import pytz
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler

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
# 定时任务的小时数 (CST)，默认北京时间早上8点
CRON_HOURS_CST = [int(h.strip()) for h in os.environ.get("CRON_HOURS", "8").split(',') if h.strip().isdigit()]

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

def _get_formatted_report():
    """获取并格式化所有 VPS 的流量报告 (核心逻辑)"""
    if not BWH_VEIDS:
        return "错误: `BWH_VEID` 环境变量未设置或为空。请确保已配置一个或多个 VEID。"

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
    return "\n".join(report_parts)

def start(update: Update, context: CallbackContext) -> None:
    """响应 /start 命令"""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        update.message.reply_text("抱歉，您无权使用此机器人。")
        return

    update.message.reply_markdown(
        f'你好，{user.mention_markdown()}! '
        f'使用 /traffic 命令来查询实时流量信息。\n\n'
        f'机器人已配置定时推送，具体时间请咨询管理员。'
    )

def get_traffic_info(update: Update, context: CallbackContext) -> None:
    """响应 /traffic 命令，查询并发送所有 VPS 的流量信息"""
    user = update.effective_user
    if AUTHORIZED_USERS and user.id not in AUTHORIZED_USERS:
        update.message.reply_text("抱歉，您无权使用此机器人。")
        return
    sent_message = update.message.reply_text("正在查询所有 VPS 的流量信息，请稍候...")
    message_id_to_delete = sent_message.message_id
    chat_id = update.message.chat_id
    final_report = _get_formatted_report()
    context.bot.delete_message(chat_id=chat_id, message_id=message_id_to_delete)
    update.message.reply_text(final_report, parse_mode='Markdown')

def send_scheduled_report(context: CallbackContext):
    """由调度器调用的函数，用于发送定时报告"""
    job = context.job
    chat_id = job.context
    logger.info(f"正在为 chat_id: {chat_id} 执行定时任务...")
    final_report = _get_formatted_report()
    context.bot.send_message(chat_id=chat_id, text=final_report, parse_mode='Markdown')

def main() -> None:
    """启动机器人并设置定时任务"""
    if not all([BWH_API_KEY, os.environ.get("TELEGRAM_BOT_TOKEN"), AUTHORIZED_USERS]):
        logger.error("错误: 缺少必要的环境变量。请检查 BWH_API_KEY, TELEGRAM_BOT_TOKEN, 和 TELEGRAM_CHAT_ID。")
        exit(1)

    updater = Updater(os.environ.get("TELEGRAM_BOT_TOKEN"), use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("traffic", get_traffic_info))
    
    # --- 设置定时任务 ---
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Shanghai'))
    if AUTHORIZED_USERS and CRON_HOURS_CST:
        for chat_id in AUTHORIZED_USERS:
            for hour in CRON_HOURS_CST:
                scheduler.add_job(
                    send_scheduled_report,
                    'cron',
                    hour=hour,
                    context=chat_id  # 传递 chat_id
                )
                logger.info(f"已为 chat_id: {chat_id} 添加了一个北京时间 {hour}:00 的定时任务。")
        scheduler.start()
    
    updater.start_polling()
    logger.info("机器人已启动，支持手动查询和定时推送。")
    updater.idle()

if __name__ == '__main__':
    main() 