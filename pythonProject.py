from typing import Union
import requests
from pprint import pprint

from typing import Optional

import os
from fastapi import FastAPI, Request
from fastapi import Depends
from pydantic import BaseModel
from dotenv import load_dotenv

from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import DateTime
from datetime import datetime, timedelta

import json

load_dotenv()

TOKEN = '6510300805:XXXXXXXXXXXXXXXXXXXXXXXXXXX'
URL = f'https://api.telegram.org/bot{TOKEN}'

DATABASE_URL = os.getenv(
    'DATABASE_URL', 'postgresql://vlada:1@localhost/todolistdb')

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()


def get_webhook_info():
    url = URL + '/getWebhookInfo'
    r = requests.get(url)
    return r.json()


pprint(get_webhook_info())


class ToDoItem(Base):
    __tablename__ = "todo_items"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    task = Column(String, index=True)
    expiration_date = Column(DateTime, default=datetime.utcnow)
    completed = Column(Boolean, default=False)


class TmpTasks(Base):
    __tablename__ = "tmp_tasks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    status = Column(String, index=True, default="wait_for_choise")
    task = Column(String, index=True, default="")
    expiration_date = Column(DateTime, default=datetime.utcnow)
    task_id_for_edit = Column(Integer, index=True, default=None)


Base.metadata.create_all(bind=engine)


class CallbackQuery(BaseModel):
    id: str
    from_user: dict
    message: Optional[dict] = None
    chat_instance: str
    data: str


class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[dict] = None
    edited_message: Optional[dict] = None
    channel_post: Optional[dict] = None
    edited_channel_post: Optional[dict] = None
    callback_query: Optional[dict] = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/webhook")
def webhook(update: TelegramUpdate, request: Request, db: Session = Depends(get_db)):
    message = update.message

    if message and 'text' in message:
        chat_id = message['chat']['id']
        text = message['text']

        add_tmp_task_if_not_exists(chat_id, db)

        task_details = get_tmp_task_details(chat_id, db)
        state = task_details["status"]
        task_id = task_details["task_id_for_edit"]

        if text == '/start':
            send_menu(chat_id)

        elif text == 'Добавить дело':
            update_tmp_task_details(
                chat_id, db, new_status="waiting_tmp_task_text")
            send_message_with_button(
                chat_id, task_id, db, "Введите текст задачи")

        elif text == 'Показать все дела':
            send_task_list(chat_id, db)

        elif state == "waiting_tmp_task_text":
            update_tmp_task_details(
                chat_id, db, new_status="waiting_date_tmp_task")
            update_tmp_task_details(chat_id, db, new_task=text)
            generate_year_selector(chat_id, datetime.now().year)

        elif state == "waiting_task_text":
            update_task_details(task_id, db, new_task=text)
            update_tmp_task_details(chat_id, db, new_status="wait_for_choise")
            send_task_details(chat_id, task_id, db)

        elif state == "waiting_date_tmp_task":
            try:
                date = datetime.strptime(text, "%Y-%m-%d")
                update_tmp_task_details(chat_id, db, new_date=date)
                task = task_details["task"]
                add_task(chat_id, task, date, db)
                update_tmp_task_details(
                    chat_id, db, new_status="wait_for_choise")
                send_message(
                    chat_id, f"Задача '{task}' с датой завершения {date.date()} добавлена.")
            except ValueError:
                send_message_with_button(
                    chat_id, task_id, db, "Ошибка. Неверный формат даты", "aboutTask")

        elif state == "waiting_date_task":
            try:
                date = datetime.strptime(text, "%Y-%m-%d")
                update_task_details(task_id, db, new_date=date)
                update_tmp_task_details(
                    chat_id, db, new_status="wait_for_choise")
                send_task_details(chat_id, task_id, db)
            except ValueError:
                send_message_with_button(
                    chat_id, task_id, db, "Ошибка. Неверный формат даты")

        elif text == 'Показать список дел по дням':
            task_list = show_user_tasks(chat_id, db)
            send_message(chat_id, task_list)
            send_menu(chat_id)

    elif update.callback_query:
        callback_data = json.loads(update.callback_query['data'])
        chat_id = update.callback_query['message']['chat']['id']
        message_id = update.callback_query['message']['message_id']
        if ("task_id" in callback_data):
            task_id = callback_data['task_id']

        delete_message(chat_id, message_id)
        if callback_data['action'] == 'go_back_to_task_list':
            send_task_list(chat_id, db)

        if callback_data['action'] == 'view_task':
            send_task_details(chat_id, task_id, db)

        elif callback_data['action'] == 'edit_task':
            update_tmp_task_details(
                chat_id, db, new_status="waiting_task_text", task_id=task_id)
            send_message_with_button(
                chat_id, task_id, db, "Введите измененный текст", "aboutTask")

        elif callback_data['action'] == 'edit_task_status':
            send_message(chat_id, "это пока не работает ибо я хз как сделать")
            send_menu(chat_id)

        elif callback_data['action'] == 'edit_task_date':
            update_tmp_task_details(
                chat_id, db, new_status="waiting_date_task", task_id=task_id)
            generate_year_selector(chat_id, datetime.now().year)

        elif callback_data['action'] == 'delete_task':
            delete_task(task_id, db)
            send_message(chat_id, "Вы избавились от одного дела!")
            send_menu(chat_id)

        elif callback_data['action'] == 'cancel':
            if task_id is not None:
                update_tmp_task_details(
                    chat_id, db, new_status="wait_for_choise", task_id=task_id)
            send_message(chat_id, "Действие отменено!")
            goTo = callback_data['goTo']
            if goTo == "menu":
                send_menu(chat_id)
            elif goTo == "aboutTask":
                send_task_details(chat_id, task_id, db)

        elif callback_data['action'] == 'set_date':
            date_str = callback_data['date']
            emulate_user_message(chat_id, date_str, db, webhook)

        elif callback_data['action'] == 'navigate_calendar':
            year = callback_data['year']
            month = callback_data['month']
            generate_calendar(chat_id, year, month)

        elif callback_data['action'] == 'select_year':
            year = callback_data['year']
            generate_calendar(chat_id, year, datetime.now().month)

        elif callback_data['action'] == 'cancel_calendar':
            generate_year_selector(chat_id, datetime.now().year)

        elif callback_data['action'] == 'cancel_year_selection':
            update_tmp_task_details(chat_id, db, new_status="wait_for_choise")
            send_message(chat_id, "Действие отменено!")
            send_menu(chat_id)

    return {"status": "ok"}


def emulate_user_message(chat_id: int, text: str, db: Session, webhook):
    fake_update = TelegramUpdate(
        update_id=0,
        message={
            "message_id": 0,
            "from": {"id": chat_id, "is_bot": False, "first_name": "User"},
            "chat": {"id": chat_id, "first_name": "User", "type": "private"},
            "date": int(datetime.now().timestamp()),
            "text": text
        }
    )
    webhook(fake_update, Request(
        scope={"type": "http"}, receive=None, send=None), db)


def generate_year_selector(chat_id, current_year):
    years = range(current_year, current_year + 6)
    buttons = []

    for year in years:
        buttons.append([{
            'text': str(year),
            'callback_data': json.dumps({'action': 'select_year', 'year': year})
        }])

    buttons.append([{'text': 'Отмена', 'callback_data': json.dumps(
        {'action': 'cancel_year_selection'})}])

    payload = {
        'chat_id': chat_id,
        'text': 'Выберите год или введите дату вручную в формате YYYY-MM-DD',
        'reply_markup': {
            'inline_keyboard': buttons
        }
    }
    url = f"{URL}/sendMessage"
    response = requests.post(url, json=payload)
    return response.json()


def generate_calendar(chat_id, year=None, month=None):
    now = datetime.now()
    if not year:
        year = now.year
    if not month:
        month = now.month

    # Создаем календарь для выбранного месяца
    calendar = []
    row = []

    # Добавляем названия дней недели
    days_of_week = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    row = [{'text': day, 'callback_data': 'ignore'} for day in days_of_week]
    calendar.append(row)

    # Получаем первый и последний день месяца
    first_day_of_month = datetime(year, month, 1)
    last_day_of_month = (first_day_of_month + timedelta(days=32)
                         ).replace(day=1) - timedelta(days=1)

    # Заполняем дни перед первым днем месяца
    current_day = first_day_of_month
    while current_day.weekday() != 0:
        current_day -= timedelta(days=1)

    # Заполняем календарь днями
    row = []
    while current_day <= last_day_of_month or current_day.weekday() != 0:
        if len(row) == 7:
            calendar.append(row)
            row = []
        if current_day < first_day_of_month or current_day > last_day_of_month:
            row.append({'text': ' ', 'callback_data': 'ignore'})
        else:
            if current_day < now:
                row.append({'text': str(current_day.day),
                           'callback_data': 'ignore'})
            else:
                row.append({
                    'text': str(current_day.day),
                    'callback_data': json.dumps({'action': 'set_date', 'date': current_day.strftime('%Y-%m-%d')})
                })
        current_day += timedelta(days=1)
    if row:
        calendar.append(row)

    # Добавляем кнопки навигации и отмены
    navigation_buttons = []

    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    navigation_buttons.append({
        'text': '<',
        'callback_data': json.dumps({'action': 'navigate_calendar', 'year': prev_year, 'month': prev_month})
    })
    navigation_buttons.append({
        'text': f'{year}-{month:02d}',
        'callback_data': json.dumps({'action': 'ignore'})
    })
    navigation_buttons.append({
        'text': '>',
        'callback_data': json.dumps({'action': 'navigate_calendar', 'year': next_year, 'month': next_month})
    })
    calendar.append(navigation_buttons)

    calendar.append(
        [{'text': 'Отмена', 'callback_data': json.dumps({'action': 'cancel_calendar'})}])

    payload = {
        'chat_id': chat_id,
        'text': 'Выберите дату или введите дату вручную в формате YYYY-MM-DD',
        'reply_markup': {
            'inline_keyboard': calendar
        }
    }
    url = f"{URL}/sendMessage"
    response = requests.post(url, json=payload)
    return response.json()


def delete_message(chat_id: int, message_id: int):
    url = f"{URL}/deleteMessage"
    payload = {
        'chat_id': chat_id,
        'message_id': message_id
    }
    response = requests.post(url, json=payload)
    return response.json()


def send_task_list(chat_id: int, db: Session):
    tasks = db.query(ToDoItem).filter(ToDoItem.user_id == chat_id).all()
    buttons = []

    for task in tasks:
        buttons.append([{
            'text': task.task,
            'callback_data': json.dumps({'action': 'view_task', 'task_id': task.id})
        }])

    inline_keyboard = {
        'inline_keyboard': buttons
    }

    payload = {
        'chat_id': chat_id,
        'text': "Список ваших дел:",
        'reply_markup': inline_keyboard
    }
    url = f"{URL}/sendMessage"
    response = requests.post(url, json=payload)
    return response.json()


def send_message_with_button(chat_id: int, task_id: int, db: Session, text: str, goTo: str = "menu"):
    task = db.query(ToDoItem).filter(ToDoItem.id == task_id).first()
    if task is None:
        id = None

    else:
        id = task.id
    button = [{'text': 'Отмена', 'callback_data': json.dumps(
        {'action': 'cancel', 'task_id': id, "goTo": goTo})}]
    inline_keyboard = {
        'inline_keyboard': [button]
    }
    payload = {
        'chat_id': chat_id,
        'text': text,
        'reply_markup': inline_keyboard
    }
    url = f"{URL}/sendMessage"
    response = requests.post(url, json=payload)
    return response.json()


def send_task_details(chat_id: int, task_id: int, db: Session):
    task = db.query(ToDoItem).filter(ToDoItem.id == task_id).first()
    if task:
        text = f"Детали задачи:\n\nЗадача: {task.task}\nСтатус: {'выполнено' if task.completed else 'еще не выполнено'}\nДата завершения: {task.expiration_date.strftime('%Y-%m-%d')}"
        buttons = [
            [{'text': 'Изменить дело', 'callback_data': json.dumps(
                {'action': 'edit_task', 'task_id': task.id})}],
            [{'text': 'Изменить статус', 'callback_data': json.dumps(
                {'action': 'edit_task_status', 'task_id': task.id})}],
            [{'text': 'Изменить дату окончания', 'callback_data': json.dumps(
                {'action': 'edit_task_date', 'task_id': task.id})}],
            [{'text': 'Удалить дело', 'callback_data': json.dumps(
                {'action': 'delete_task', 'task_id': task.id})}],
            [{'text': 'Назад', 'callback_data': json.dumps(
                {'action': 'go_back_to_task_list', 'task_id': task.id})}]
        ]
        inline_keyboard = {
            'inline_keyboard': buttons
        }
        payload = {
            'chat_id': chat_id,
            'text': text,
            'reply_markup': inline_keyboard
        }
        url = f"{URL}/sendMessage"
        response = requests.post(url, json=payload)
        return response.json()

    else:
        send_message(chat_id, "Задача не найдена.")


def add_tmp_task_if_not_exists(user_id: int, db: Session):
    tmp_task = db.query(TmpTasks).filter(TmpTasks.user_id == user_id).first()
    if not tmp_task:
        new_user = TmpTasks(user_id=user_id)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user
    return tmp_task


def get_tmp_task_details(user_id: int, db: Session):
    tmp_task = db.query(TmpTasks).filter(TmpTasks.user_id == user_id).first()
    if tmp_task:
        return {
            "status": tmp_task.status,
            "task": tmp_task.task,
            "task_id_for_edit": tmp_task.task_id_for_edit
        }
    return None


def delete_task(task_id: int, db: Session):
    try:
        task = db.query(ToDoItem).filter(ToDoItem.id == task_id).first()
        db.delete(task)
        db.commit()
    except Exception as e:
        db.rollback()  # Откат транзакции в случае ошибки
        return {"error": str(e)}


def update_task_details(task_id: int, db: Session, new_task: str = None, new_date: datetime = None):
    task = db.query(ToDoItem).filter(ToDoItem.id == task_id).first()

    if task:
        if new_task is not None:
            task.task = new_task
        if new_date is not None:
            task.expiration_date = new_date
        db.commit()
        db.refresh(task)
        return task
    return None


def update_tmp_task_details(user_id: int, db: Session, new_status: str = None, new_task: str = None, new_date: datetime = None, task_id: int = None):
    task = db.query(TmpTasks).filter(TmpTasks.user_id == user_id).first()

    if task:
        if task_id is not None:
            task.task_id_for_edit = task_id
        if new_status is not None:
            task.status = new_status
        if new_task is not None:
            task.task = new_task
        if new_date is not None:
            task.expiration_date = new_date
        if task_id is not None:
            task.task_id_in_todo_items = task_id
        db.commit()
        db.refresh(task)
        return task
    return None


def add_task(user_id: int, task: str, due_date: datetime, db: Session):
    db_task = ToDoItem(user_id=user_id, task=task, expiration_date=due_date)
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


def show_user_tasks(user_id: int, db: Session):
    tasks = db.query(ToDoItem).filter(ToDoItem.user_id == user_id).all()
    if tasks:
        task_list = format_task_list(tasks)
        return task_list
    else:
        return "У вас нет задач, поздравляем!"


def format_task_list(tasks):
    formatted_tasks = []
    current_date = None
    i = 1
    for j, task in enumerate(tasks, start=1):
        task_date = task.expiration_date.strftime('%Y-%m-%d')
        if task_date != current_date:
            i = 1
            current_date = task_date
            if (j > 1):
                formatted_tasks.append("")
            formatted_tasks.append(f"Дата окончания срока: {task_date}")

        status = "еще не выполнено" if not task.completed else "выполнено"
        formatted_tasks.append(
            f"{i}) \"{task.task}\"\n      статус: \"{status}\"\n      id: \"{task.id}\"")
        i += 1

    return "\n".join(formatted_tasks)


def send_message(chat_id: int, text: str):
    url = f"{URL}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text
    }
    response = requests.post(url, json=payload)
    return response.json()


def send_menu(chat_id: int):
    url = f"{URL}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': "Выберите опцию:",
        'reply_markup': {
            'keyboard': [
                [{'text': 'Добавить дело'}],
                [{'text': 'Показать все дела'}],
                [{'text': 'Показать список дел по дням'}]
            ],
            'resize_keyboard': True,
            'one_time_keyboard': True
        }
    }
    response = requests.post(url, json=payload)

    return response.json()


@app.get("/")
def read_root():
    bot_description = "Добро пожаловать в 'To Do List Bot' – вашего личного помощника для управления списками дел! С помощью этого бота вы сможете легко и удобно создавать, редактировать и просматривать свои задачи прямо в Telegram."
    return {"message": bot_description}
