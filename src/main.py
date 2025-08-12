import os
import requests
import datetime
import logging
import pytz
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler
from telegram.error import TelegramError
from telegram import ParseMode

# 启用日志记录
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 环境变量配置 ---
# 全新的凭证变量，格式为 "VEID1:API_KEY1;VEID2:API_KEY2"
BWH_VARS_STR = os.environ.get("BWH_VARS")
BWH_CREDS = []
if BWH_VARS_STR:
    for pair in BWH_VARS_STR.split(';'):
        if ':' in pair:
            veid, api_key = pair.split(':', 1)
            BWH_CREDS.append({'veid': veid.strip(), 'api_key': api_key.strip()})

# 将 Chat ID 作为授权用户列表
AUTHORIZED_USERS = [int(user_id.strip()) for user_id in os.environ.get("TELEGRAM_CHAT_ID", "").split(',') if user_id.strip()]
# 定时任务的小时数 (CST)，默认北京时间早上8点
CRON_HOURS_CST = [int(h.strip()) for h in os.environ.get("CRON_HOURS", "8").split(',') if h.strip().isdigit()]


def get_bwh_service_info(veid, api_key):
    """通过搬瓦工 API 获取指定 VEID 的 VPS 服务信息"""
    if not veid or not api_key:
        return None, "VEID 或 API Key 未提供。"

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


def create_progress_bar(percentage, width=12):
    """
    Creates a text-based progress bar.
    Example: [████▍·······]
    """
    if percentage <= 0:
        return f"[{'·' * width}]"
    if percentage >= 100:
        return f"[{'█' * width}]"

    progress_ratio = percentage / 100.0
    filled_count = progress_ratio * width
    
    full_blocks = int(filled_count)
    
    # partial_blocks represents 1/8 to 7/8 of a block
    partial_blocks = ['▏', '▎', '▍', '▌', '▋', '▊', '▉']
    
    partial_amount = filled_count - full_blocks
    partial_index = int(partial_amount * 8)
    
    bar = '█' * full_blocks
    
    if full_blocks < width:
        if partial_index > 0 and partial_index <= len(partial_blocks):
            bar += partial_blocks[partial_index - 1]
        elif full_blocks == 0 and percentage > 0:
            # For very small percentages, show the smallest possible bar
            bar += '▏'

    empty_char = '·'
    empty_count = width - len(bar)
    bar += empty_char * empty_count

    return f"[{bar}]"


def _get_cycle_start_date(end_date):
    """根据周期结束日期估算周期开始日期（按月计）。"""
    # 移动到结束日期所在月份的第一天
    first_day_of_end_month = end_date.replace(day=1)
    # 再往前推一天，得到上个月的最后一天
    last_day_of_previous_month = first_day_of_end_month - datetime.timedelta(days=1)
    
    try:
        # 尝试将日期设置为与结束日期相同的“日”
        start_date = last_day_of_previous_month.replace(day=end_date.day)
    except ValueError:
        # 如果“日”无效（例如，尝试从3月31日回到2月31日），
        # 则将开始日期定为上个月的最后一天（例如，2月28日或29日）。
        start_date = last_day_of_previous_month
        
    return start_date


def _get_formatted_report():
    """获取并格式化所有 VPS 的流量报告 (核心逻辑)"""
    if not BWH_CREDS:
        return "错误: `BWH_VARS` 环境变量未设置或格式不正确。请确保格式为 'VEID1:API_KEY1;VEID2:API_KEY2'。"

    report_parts = ["*VPS 流量总报告*"]

    for cred in BWH_CREDS:
        veid = cred['veid']
        api_key = cred['api_key']
        info, error_message = get_bwh_service_info(veid, api_key)
        
        if error_message:
            report_parts.append(f"\n------\n*VPS (VEID: `{veid}`)*\n查询失败: `{error_message}`")
            continue
        
        if info:
            plan_monthly_data = info.get("plan_monthly_data")
            data_counter = info.get("data_counter")
            data_next_reset_ts = info.get("data_next_reset")
            data_next_reset_str = datetime.datetime.fromtimestamp(data_next_reset_ts).strftime('%Y-%m-%d')
            
            # --- 计算时间进度 ---
            time_percent = 0.0
            if data_next_reset_ts:
                utc_tz = pytz.utc
                reset_date_utc = datetime.datetime.fromtimestamp(data_next_reset_ts, tz=utc_tz)
                start_date_utc = _get_cycle_start_date(reset_date_utc)
                now_utc = datetime.datetime.now(utc_tz)
                
                cycle_duration = (reset_date_utc - start_date_utc).total_seconds()
                elapsed_time = (now_utc - start_date_utc).total_seconds()

                if cycle_duration > 0:
                    raw_time_percent = (elapsed_time / cycle_duration) * 100
                    # 将结果限制在 0-100 之间，并保留一位小数
                    time_percent = round(max(0, min(100, raw_time_percent)), 1)

            used_gb = format_bytes(data_counter)
            total_gb = format_bytes(plan_monthly_data)
            
            usage_percent = 0
            if plan_monthly_data and data_counter and plan_monthly_data > 0:
                usage_percent = round((data_counter / plan_monthly_data) * 100, 2)
            
            progress_bar = create_progress_bar(usage_percent)

            part = (
                f"\n------\n"
                f"🖥️ *主机:* `{info.get('hostname')}`\n"
                f"📈 *流量:* `{used_gb} GB` / `{total_gb} GB`\n"
                f"📊 *使用率:* {progress_bar} `{usage_percent}%` (⏳: `{time_percent}%`)\n"
                f"📅 *重置日期:* `{data_next_reset_str}`"
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


def send_traffic_report(bot: Bot, chat_id: int):
    """由调度器调用的函数，用于发送定时报告"""
    logger.info(f"正在为 chat_id: {chat_id} 执行定时任务...")
    try:
        final_report = _get_formatted_report()
        bot.send_message(chat_id=chat_id, text=final_report, parse_mode='Markdown')
        logger.info(f"已成功向 chat_id: {chat_id} 发送定时报告。")
    except Exception as e:
        logger.error(f"向 chat_id: {chat_id} 发送定时报告失败: {e}")


def send_startup_notification(bot: Bot, chat_id: int):
    """在机器人启动时发送通知。"""
    logger.info(f"正在向 chat_id: {chat_id} 发送启动通知...")
    try:
        cst = pytz.timezone('Asia/Shanghai')
        now = datetime.datetime.now(cst).strftime('%Y-%m-%d %H:%M:%S')
        
        message = (
            "✅ *机器人部署成功*\n\n"
            f"我已于北京时间 `{now}` 成功启动或重启，\n"
            f"现在可以接收您的命令了。\n\n"
            f"使用 /traffic 来查询流量吧！"
        )
        bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        logger.info(f"已成功向 chat_id: {chat_id} 发送启动通知。")
    except Exception as e:
        logger.error(f"向 chat_id: {chat_id} 发送启动通知失败: {e}")


def main() -> None:
    """启动机器人并设置定时任务"""
    if not all([BWH_VARS_STR, os.environ.get("TELEGRAM_BOT_TOKEN"), AUTHORIZED_USERS]):
        logger.error("错误: 缺少必要的环境变量。请检查 BWH_VARS, TELEGRAM_BOT_TOKEN, 和 TELEGRAM_CHAT_ID。")
        exit(1)

    updater = Updater(os.environ.get("TELEGRAM_BOT_TOKEN"), use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("traffic", get_traffic_info))
    
    # --- 设置定时任务 ---
    if BWH_CREDS and AUTHORIZED_USERS and CRON_HOURS_CST:
        scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Shanghai'))
        for chat_id in AUTHORIZED_USERS:
            for hour in CRON_HOURS_CST:
                scheduler.add_job(
                    send_traffic_report,
                    'cron',
                    hour=hour,
                    kwargs={'bot': updater.bot, 'chat_id': chat_id}
                )
                logger.info(f"已为 chat_id: {chat_id} 添加了一个北京时间 {hour}:00 的定时任务。")
        scheduler.start()
    
    updater.start_polling()
    logger.info("机器人已启动，支持多 VPS (VEID:API_KEY) 查询。")

    # --- 发送启动通知给所有授权用户 ---
    for chat_id in AUTHORIZED_USERS:
        send_startup_notification(updater.bot, chat_id)

    updater.idle()

if __name__ == '__main__':
    main() 