#!/usr/bin/env python3

import json
import requests
import time
import urllib
from datetime import datetime

import sqlalchemy

import db
from db import Task

import os

TOKEN = os.environ['SECRET_TOKEN']
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
USERNAME = os.environ['USERNAME']
REPO_NAME = os.environ['REPO_NAME']
REPO_OWNER = os.environ['REPO_OWNER']
URL = "https://api.telegram.org/bot{}/".format(TOKEN)

STATUS_COMMANDS = [
    '/todo',
    '/doing',
    '/done'
]

ICONS = {
    'TODO': '\U0001F195',
    'DOING': '\U000023FA',
    'DONE': '\U00002611',
    'status': '\U0001F4DD',
    'status_list': '\U0001F4CB',
    'low': '\U00002755',
    'medium': '\U00002757',
    'high': '\U0000203C'
}

HELP = """
 /new NOME
 /todo ID...
 /doing ID...
 /done ID...
 /delete ID
 /list
 /duedate ID DUEDATE{AAAA/MM/DD}
 /rename ID NOME
 /dependson ID ID...
 /duplicate ID
 /priority ID PRIORITY{low, medium, high}
 /help
"""


def make_github_issue(title, body=None):
    url = 'https://api.github.com/repos/%s/%s/import/issues' % (REPO_OWNER,
                                                                REPO_NAME)

    headers = {
        "Authorization": "token %s" % GITHUB_TOKEN,
        "Accept": "application/vnd.github.golden-comet-preview+json"
    }

    data = {
        'issue': {
            'title': title,
            'body': body,
        }
    }

    payload = json.dumps(data)
    response = requests.request("POST", url, data=payload, headers=headers)

    if response.status_code == 202:
        print ('Successfully created Issue "%s"' % title)
    else:
        print ('Could not create Issue "%s"' % title)
        print ('Response:', response.content)


def get_url(url):
    response = requests.get(url)
    content = response.content.decode("utf8")
    return content


def get_json_from_url(url):
    content = get_url(url)
    js = json.loads(content)
    return js


def get_updates(offset=None):
    url = URL + "getUpdates?timeout=100"
    if offset:
        url += "&offset={}".format(offset)
    js = get_json_from_url(url)
    return js


def send_message(text, chat_id, reply_markup=None):
    text = urllib.parse.quote_plus(text)
    url = URL + "sendMessage?text={}&chat_id={}&parse_mode=Markdown".format(
          text, chat_id)
    if reply_markup:
        url += "&reply_markup={}".format(reply_markup)
    get_url(url)


def get_last_update_id(updates):
    update_ids = []
    for update in updates["result"]:
        update_ids.append(int(update["update_id"]))

    return max(update_ids)


def get_cleared_info(msg):
    text = ''
    if len(msg.split(' ', 1)) > 1:
        text = msg.split(' ', 1)[1]
    msg = msg.split(' ', 1)[0]
    return msg, text


def deps_text(task, chat, preceed=''):
    text = ''

    for i in range(len(task.dependencies.split(',')[:-1])):
        line = preceed
        query = db.session.query(Task).filter_by(id=int(
                task.dependencies.split(',')[:-1][i]), chat=chat)
        dependeci = query.one()

        icon = ICONS[dependeci.status]

        if i + 1 == len(task.dependencies.split(',')[:-1]):
            line += '└── [[{}]] {} {}\n'.format(
                    dependeci.id, icon, dependeci.name)
            line += deps_text(dependeci, chat, preceed + '    ')
        else:
            line += '├── [[{}]] {} {}\n'.format(
                    dependeci.id, icon, dependeci.name)
            line += deps_text(dependeci, chat, preceed + '│   ')

        text += line
    return text


def new_task(chat, msg):
    task = Task(chat=chat, name=msg, status='TODO', dependencies='',
                parents='', priority='', duedate=None)
    db.session.add(task)
    db.session.commit()
    make_github_issue(title=msg, body="New task *TODO* [{}] {}".format(
                      task.id, task.name))
    send_message("New task *TODO* [[{}]] {}".format(task.id, task.name), chat)


def rename_task(chat, msg):
    if msg != '':
        msg, text = get_cleared_info(msg)
        task = find_id_task(msg, chat)

        if task is False:
            return

        if text == '':
            send_message("You want to modify task {}, but you\
                         didn't provide any new text".format(task.id), chat)
            return

        old_text = task.name
        task.name = text
        db.session.commit()
        send_message("Task {} redefined from {} to {}".format(
                     task.id, old_text, text), chat)
    else:
        send_message("You must inform one id", chat)


def duplicate_task(chat, msg):
        task = find_id_task(msg, chat)

        if task is False:
            return

        duplicated_task = Task(chat=task.chat, name=task.name,
                               status=task.status,
                               dependencies=task.dependencies,
                               parents=task.parents, priority=task.priority,
                               duedate=task.duedate)
        db.session.add(duplicated_task)

        for i in task.dependencies.split(',')[:-1]:
            query = db.session.query(Task).filter_by(id=int(i), chat=chat)
            i = query.one()
            task.parents += '{},'.format(duplicated_task.id)

        db.session.commit()
        send_message("New task *TODO* [[{}]] {}".format(
                     duplicated_task.id, duplicated_task.name), chat)


def delete_task(chat, msg):
        task = find_id_task(msg, chat)

        if task is False:
            return

        for i in task.dependencies.split(',')[:-1]:
            query = db.session.query(Task).filter_by(id=int(i), chat=chat)
            temp = query.one()
            temp.parents = temp.parents.replace('{},'.format(task.id), '')

        for i in task.parents.split(',')[:-1]:
            query = db.session.query(Task).filter_by(id=int(i), chat=chat)
            temp = query.one()
            temp.dependencies = temp.dependencies.replace('{},'.format(
                                                          task.id), '')

        db.session.delete(task)
        db.session.commit()
        send_message("Task [[{}]] deleted".format(task.id), chat)


def status_task(chat, status, msg):
        task_list = msg.split(" ")
        for i in task_list:
            task = find_id_task(i, chat)

            if task is False:
                return

            task.status = status
            db.session.commit()
            send_message("*{}* task [[{}]] {}".format(status,
                         task.id, task.name), chat)


def list_task(chat):
    list = ''
    list += '{} Task List\n'.format(ICONS['status_list'])

    query = db.session.query(Task).filter_by(parents='',
                                             chat=chat).order_by(Task.id)

    for task in query.all():
        icon = ICONS[task.status]

        list += '[[{}]] {} {} *{}*\n'.format(task.id, icon, task.name,
                                             task.priority)
        list += deps_text(task, chat)

    send_message(list, chat)
    list = ''

    list += '{} _Status_\n'.format(ICONS['status_list'])
    query = create_list('TODO', chat)
    list += '\n{} *TODO*\n'.format(ICONS['TODO'])
    for task in query.all():
        duedate = duedate_to_string(task.duedate)

        if(task.priority == ''):
            list += '[[{}]] {} *{}* *{}*\n'.format(task.id, task.name,
                                                   task.priority, duedate)
        else:
            list += '[[{}]] {} *{}* {} *{}*\n'.format(task.id, task.name,
                                                      task.priority,
                                                      ICONS[task.priority],
                                                      duedate)

    query = create_list('DOING', chat)
    list += '\n{} *DOING*\n'.format(ICONS['DOING'])
    for task in query.all():
        duedate = duedate_to_string(task.duedate)

        if(task.priority == ''):
            list += '[[{}]] {} *{}* *{}*\n'.format(task.id, task.name,
                                                   task.priority, duedate)
        else:
            list += '[[{}]] {} *{}* {} *{}*\n'.format(task.id, task.name,
                                                      task.priority,
                                                      ICONS[task.priority],
                                                      duedate)

    query = create_list('DONE', chat)
    list += '\n{} *DONE*\n'.format(ICONS['DONE'])
    for task in query.all():
        duedate = duedate_to_string(task.duedate)

        if(task.priority == ''):
            list += '[[{}]] {} *{}* *{}*\n'.format(task.id, task.name,
                                                   task.priority, duedate)
        else:
            list += '[[{}]] {} *{}* {} *{}*\n'.format(task.id, task.name,
                                                      task.priority,
                                                      ICONS[task.priority],
                                                      duedate)

    send_message(list, chat)


def create_list(status, chat):
    return db.session.query(Task).filter_by(status=status,
                                            chat=chat).order_by(Task.id)


def duedate_to_string(task_duedate):
    return ('' if task_duedate is None else task_duedate.strftime('%Y/%m/%d'))


def dependeci_task(chat, msg):
    if msg != '':
        msg, text = get_cleared_info(msg)

        task = find_id_task(msg, chat)
        if task is False:
            return

        if text == '':
            for i in task.dependencies.split(',')[:-1]:
                i = int(i)
                query = db.session.query(Task).filter_by(id=i, chat=chat)
                tasks = query.one()
                tasks.parents = tasks.parents.replace('{},'.format(task.id),
                                                      '')

            task.dependencies = ''
            send_message("Dependencies removed from task {}".format(task.id),
                         chat)
        else:
            for dependeci_id in text.split(' '):
                if not dependeci_id.isdigit():
                    send_message("All dependencies ids must be numeric,\
                                 and not {}".format(dependeci_id), chat)
                elif int(dependeci_id) == task.id:
                    send_message("I'm sorry. Invalid operation.", chat)

                elif verify_circle_referece(task.id, dependeci_id, chat):
                    send_message("I'm sorry. This operation generates circle\
                                 reference", chat)

                else:
                    dependeci_id = int(dependeci_id)
                    query = db.session.query(Task).filter_by(id=dependeci_id,
                                                             chat=chat)
                    try:
                        task_dependeci = query.one()
                        task_dependeci.parents += str(task.id) + ','
                    except sqlalchemy.orm.exc.NoResultFound:
                        send_message("_404_ Task {} not found x.x".format(
                                     dependeci_id), chat)
                        continue

                    dependeci_list = task.dependencies.split(',')
                    if str(dependeci_id) not in dependeci_list:
                        task.dependencies += str(dependeci_id) + ','
        db.session.commit()
        send_message("Task {} dependencies up to date".format(msg), chat)
    else:
        send_message("You must inform one id", chat)


def verify_circle_referece(task_id, dependeci_id, chat):
    task = find_id_task(str(task_id), chat)
    if task is False:
        return True
    if str(dependeci_id) in task.parents.split(',')[:-1]:
        return True
    for i in task.parents.split(',')[:-1]:
        if verify_circle_referece(i, dependeci_id, chat):
            return True
    return False


def priority_task(chat, msg):
    if msg != '':
        msg, text = get_cleared_info(msg)

        task = find_id_task(msg, chat)
        if task is False:
            return

        if text == '':
            task.priority = ''
            send_message("_Cleared_ all priorities from task {}".format(
                         task.id), chat)
        else:
            if text.lower() not in ['high', 'medium', 'low']:
                send_message("The priority *must be* one of the following:\
                             high, medium, low", chat)
            else:

                task.priority = text.lower()
                send_message("*Task {}* priority has priority *{}* {}".format(
                             task.id, text.lower(), ICONS[task.priority]),
                             chat)

        db.session.commit()
    else:
        send_message("You must inform one id", chat)


def find_id_task(task_id, chat):
    if not task_id.isdigit():
        send_message("You must inform the task id", chat)
        return False

    task_id = int(task_id)
    query = db.session.query(Task).filter_by(id=task_id, chat=chat)

    try:
        task = query.one()
        return task
    except sqlalchemy.orm.exc.NoResultFound:
        send_message("_404_ Task {} not found x.x".format(task_id), chat)
        return False


def extract_useful_info(message):
    if "text" not in message.keys():
        message["text"] = "/start"

    if "first_name" not in message["chat"].keys():
        message["chat"]["first_name"] = "Grupo"

    command = message["text"].split(" ", 1)[0]
    chat = message["chat"]["id"]
    user = message["chat"]["first_name"]

    msg = ''
    if len(message["text"].split(" ", 1)) > 1:
        msg = message["text"].split(" ", 1)[1].strip()

    return command, msg, chat, user


def duedate_task(chat, msg):
    if msg != '':
        msg, text = get_cleared_info(msg)

    task = find_id_task(msg, chat)
    if task is False:
        return

    task_id = int(msg)

    if text == '':
        task.duedate = None
        send_message("_Cleared_ duedate from task {}".format(task_id), chat)
        db.session.commit()
        return

    text = text.split("/")
    try:
        task.duedate = datetime.strptime(" ".join(text), '%Y %m %d')
        send_message("*Task {}* due date has due date *{}*".format(task_id,
                     task.duedate), chat)
        db.session.commit()
    except ValueError:
        send_message("The duedate format is incorrect ! Try again", chat)


def handle_updates(updates):
    for update in updates["result"]:
        if 'message' in update:
            message = update['message']
        elif 'edited_message' in update:
            message = update['edited_message']
        else:
            print('Can\'t process! {}'.format(update))
            return

        command, msg, chat, user = extract_useful_info(message)

        print(command, msg, chat)

        if command == '/new':
            new_task(chat, msg)

        elif command == '/rename':
            rename_task(chat, msg)

        elif command == '/duplicate':
            duplicate_task(chat, msg)

        elif command == '/delete':
            delete_task(chat, msg)

        elif command in STATUS_COMMANDS:
            status = command.replace(command, command.upper().replace('/', ''))
            status_task(chat, status, msg)

        elif command == '/list':
            list_task(chat)

        elif command == '/dependson':
            dependeci_task(chat, msg)

        elif command == '/priority':
            priority_task(chat, msg)

        elif command == '/start' or command == '/help':
            send_message("Here is a list of things you can do.", chat)
            send_message(HELP, chat)

        elif command == '/duedate':
            duedate_task(chat, msg)

        else:
            send_message("I'm sorry {}. I'm afraid I can't do that.".format(
                         user), chat)


def main():
    last_update_id = None

    while True:
        print("Updates")
        updates = get_updates(last_update_id)

        if len(updates["result"]) > 0:
            last_update_id = get_last_update_id(updates) + 1
            handle_updates(updates)

        time.sleep(0.5)


if __name__ == '__main__':
    main()
