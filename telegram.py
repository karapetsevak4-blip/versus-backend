import asyncio
import os
import sys
import logging
from aiogram import Bot, Dispatcher, types, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart,Command, CommandObject
from aiogram.types import InlineKeyboardButton, WebAppInfo, InlineKeyboardMarkup, LabeledPrice, Message, \
    SuccessfulPayment, PreCheckoutQuery
from aiogram.client.default import DefaultBotProperties
from decimal import Decimal
from asgiref.sync import sync_to_async
from dotenv import load_dotenv
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()
load_dotenv()
from main.models import *
from django.conf import settings
from main.test_mode import closed_test_mode, telegram_user_allowed, require_financial_operations
# from main.service import buy_something, upgrade_something

# Bot token can be obtained via https://t.me/BotFather
TOKEN = settings.TELEGRAM_BOT_TOKEN
# Initialize Bot instance with default bot properties which will be passed to all API calls

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# All handlers should be attached to the Dispatcher
dp = Dispatcher()
payment_router = Router()


@dp.message(CommandStart())
async def handle_start(message: types.Message):
    if not message.from_user or not telegram_user_allowed(message.from_user.id):
        return
    command_parts = message.text.split()
    link=os.getenv('FRONT_URL')
    if len(command_parts) > 1:
        # referrer_id = command_parts[1].replace('id_', '')  # Удаляем префикс 'id_'
        ref_data = command_parts[1]
        ref_parts = ref_data.replace("id_", "").split("_")

        # Извлекаем ID (первая часть) и имя (вторая часть, если есть)
        referrer_id = ref_parts[0]
        web_app_url = f'{link}?refer_id={referrer_id}'

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Запуск", web_app=WebAppInfo(url=web_app_url))]
        ])
        await message.answer("Начни сейчас и догони своего друга", reply_markup=keyboard)
    else:
        web_app_url = f'{link}'
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Запуск", web_app=WebAppInfo(url=web_app_url))]
        ])
        await message.answer("Попробуй свои силы и зарабатывай", reply_markup=keyboard)


async def create_invoice_link(price: int,id:int) -> str:
    require_financial_operations()
    prices = [LabeledPrice(label='Donate', amount=price)]
    async with AiohttpSession() as session:
        bot = Bot(token=TOKEN, session=session)
        invoice_link = await bot.create_invoice_link(
            title=f'Buy donation currency in the amount of :{price}',  # Заголовок счета
            description='Paid',  # Описание счета
            provider_token='',
            currency="XTR",  # Используйте поддерживаемую валюту
            prices=prices,
            payload=f"order_id:{id}"  # Уникальный идентификатор платежа
        )

        return invoice_link


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    if closed_test_mode():
        await pre_checkout_query.answer(ok=False, error_message='Платежи на тестовом стенде отключены.')
        return
    await pre_checkout_query.answer(ok=True)


@payment_router.message(lambda message: message.successful_payment is not None)
async def successful_payment(message: Message):
    """ Обрабатываем успешную оплату """
    if closed_test_mode():
        logging.error('Payment update received in closed test mode; financial processing blocked')
        return
    payment_info: SuccessfulPayment = message.successful_payment
    payload = payment_info.invoice_payload
    order_id = payload.split(":")[1]  # Получаем ID заказа

    try:
        transaction = await Transaction.objects.filter(id=order_id).select_related('user__user_balance').afirst()
        season = await Season.objects.filter(active=True).afirst()
        transaction.completed = True
        user = transaction.user
        user.user_balance.token_money += transaction.price
        await distribute_rewards(user.id,transaction.price)

        if season:
            season.prize += int(transaction.price * 0.25)
            await season.asave()
        await transaction.user.user_balance.asave()
        await transaction.asave()

    except Exception as e:
        print(e)


@dp.message(Command('refund'))
async def commandrefund_handler(message: Message, bot: Bot, command: CommandObject):
    if closed_test_mode():
        return
    transaction_id = command.args
    try:
        await bot.refund_star_payment(
            user_id=message.from_user.id,
            telegram_payment_charge_id=transaction_id
        )
    except Exception as e:
        print(e)

LEVEL_PERCENTAGES = [
    Decimal('0.10'),
    Decimal('0.07'),
    Decimal('0.04'),
    Decimal('0.03'),
    Decimal('0.01'),
]

async def distribute_rewards(user_id, purchase_amount):
    require_financial_operations()
    user = await User.objects.select_related(
        'user_balance', 'referrer__user_balance'
    ).aget(id=user_id)

    referrer = user.referrer
    level = 0
    visited = set()

    while referrer and level < len(LEVEL_PERCENTAGES):
        if referrer.id in visited:
            break
        visited.add(referrer.id)

        if not hasattr(referrer, 'user_balance'):
            break

        reward = Decimal(purchase_amount) * LEVEL_PERCENTAGES[level]

        referrer.user_balance.token_money += reward
        await referrer.user_balance.asave(update_fields=['token_money'])

        referrer = referrer.referrer
        level += 1



async def main() -> None:
    if closed_test_mode():
        identity = await bot.get_me()
        if identity.id != settings.TELEGRAM_TEST_BOT_ID:
            raise RuntimeError('Bot identity does not match the configured test bot')
    webhook = await bot.get_webhook_info()
    if webhook.url:
        raise RuntimeError('Webhook is configured; polling will not change or delete it')
    dp.include_router(payment_router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
