import os
import time
import threading
import webbrowser
import json
from datetime import datetime
from urllib.parse import parse_qs

import vk_api
import customtkinter as ctk

APP_NAME = "VK Dialog Parser"
APP_VERSION = "1.0"
CONFIG_FILE = "config.json"
APP_AUTHOR = "abshka"

DELAY = 0.34  # пауза между запросами к VK API


def ensure_dir(path: str):
    """Создание папки, если её нет."""
    if not os.path.exists(path):
        os.makedirs(path)


def sanitize(name: str) -> str:
    """Убираем запрещённые символы Windows из имени файла."""
    bad = '<>:"/\\|?*'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip()


def extract_token(text: str) -> str | None:
    """
    Принимает либо чистый токен, либо полную ссылку из адресной строки.
    Поддерживает формат vkhost и OAuth-ссылок с access_token в фрагменте.
    """
    t = text.strip()

    # Если похоже на "vk1.a.XXXX" — сразу возвращаем
    if "access_token=" not in t and "vk1.a." in t:
        return t

    # access_token может быть в части после '#'
    if "access_token=" in t:
        parts = t.split("#", 1)
        if len(parts) == 2:
            fragment = parts[1]
        else:
            fragment = t.split("?", 1)[-1]

        parsed = parse_qs(fragment, keep_blank_values=True)
        token_list = parsed.get("access_token")
        if token_list and token_list[0]:
            return token_list[0]

        start = t.find("access_token=")
        if start != -1:
            start += len("access_token=")
            end = t.find("&", start)
            if end == -1:
                return t[start:]
            return t[start:end]

    return None


def load_config() -> dict:
    """Загружает конфигурацию из файла."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}


def save_config(config: dict):
    """Сохраняет конфигурацию в файл."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Не удалось сохранить конфиг: {e}")


def format_timestamp(ts: int) -> str:
    """Форматирует Unix timestamp в читаемый формат."""
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_user_info(vk, user_id: int) -> dict:
    """Получает информацию о пользователе."""
    try:
        info = vk.users.get(user_ids=user_id)[0]
        return {
            "id": user_id,
            "first_name": info.get("first_name", ""),
            "last_name": info.get("last_name", ""),
            "full_name": f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
        }
    except:
        return {
            "id": user_id,
            "first_name": "",
            "last_name": "",
            "full_name": f"id{user_id}"
        }


def get_chat_info(vk, chat_id: int) -> dict:
    """Получает информацию о беседе."""
    try:
        peer_id = 2000000000 + chat_id
        resp = vk.messages.getConversationsById(peer_ids=peer_id)
        items = resp.get("items", [])
        if items:
            chat = items[0].get("chat_settings", {})
            return {
                "id": peer_id,
                "title": chat.get("title", f"Беседа {chat_id}"),
                "members_count": chat.get("members_count", 0)
            }
    except:
        pass
    return {
        "id": 2000000000 + chat_id,
        "title": f"Беседа {chat_id}",
        "members_count": 0
    }


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Загружаем конфиг
        self.config_data = load_config()
        last_token = self.config_data.get("last_token")
        self._initial_token = last_token or ""

        # Настройки внешнего вида
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("700x750")
        self.resizable(False, False)

        # Иконка окна
        base_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "assets", "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                print(f"Не удалось установить иконку окна: {e}")

        # ---------- Заголовок ----------
        self.label_title = ctk.CTkLabel(
            self,
            text=APP_NAME,
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self.label_title.pack(pady=(15, 5))

        self.label_sub = ctk.CTkLabel(
            self,
            text="Экспортирует диалоги ВКонтакте в формат Markdown с сохранением имен и временных меток.",
            font=ctk.CTkFont(size=13),
            wraplength=650,
        )
        self.label_sub.pack(pady=(0, 5))

        self.label_author = ctk.CTkLabel(
            self,
            text=f"Автор: {APP_AUTHOR}",
            font=ctk.CTkFont(size=11),
        )
        self.label_author.pack(pady=(0, 10))

        # ---------- Поля ввода ----------
        self.frame_inputs = ctk.CTkFrame(self)
        self.frame_inputs.pack(fill="x", padx=0, pady=10)

        # Токен
        self.label_token = ctk.CTkLabel(self.frame_inputs, text="Access token:")
        self.label_token.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=(10, 5))

        self.entry_token = ctk.CTkEntry(
            self.frame_inputs,
            width=480,
            show="*",
            placeholder_text="Вставьте токен или полную ссылку после авторизации",
        )
        self.entry_token.grid(row=1, column=0, padx=0, pady=(0, 0), sticky="w")

        if self._initial_token:
            self.entry_token.insert(0, self._initial_token)

        # Горячие клавиши для токена
        def _token_key_handler(event):
            code = event.keycode
            ctrl = (event.state & 0x4) != 0

            if not ctrl:
                return

            if code == 86:  # Ctrl+V
                try:
                    text = self.clipboard_get()
                    pos = self.entry_token.index("insert")
                    self.entry_token.insert(pos, text)
                except Exception:
                    pass
                return "break"

            if code == 67:  # Ctrl+C
                try:
                    text = self.entry_token.get()
                    self.clipboard_clear()
                    self.clipboard_append(text)
                except Exception:
                    pass
                return "break"

            if code == 65:  # Ctrl+A
                try:
                    self.entry_token.select_range(0, "end")
                    self.entry_token.icursor("end")
                except Exception:
                    pass
                return "break"

        self.entry_token.bind("<KeyPress>", _token_key_handler)

        # Кнопка "Получить токен"
        self.button_get_token = ctk.CTkButton(
            self.frame_inputs,
            text="Получить токен",
            width=100,
            command=self.open_token_page,
        )
        self.button_get_token.grid(row=1, column=1, padx=(0, 0), pady=(0, 0), sticky="e")

        self.label_token_help = ctk.CTkLabel(
            self.frame_inputs,
            text="Нажмите кнопку выше, авторизуйтесь (права: messages, offline), скопируйте всю ссылку из адресной строки.",
            font=ctk.CTkFont(size=11),
            wraplength=620,
        )
        self.label_token_help.grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 10))

        # ---------- Выбор диалогов ----------
        self.label_dialogs = ctk.CTkLabel(
            self.frame_inputs,
            text="Выберите диалоги для экспорта:",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.label_dialogs.grid(row=3, column=0, columnspan=2, sticky="w", padx=5, pady=(10, 5))

        self.button_load_dialogs = ctk.CTkButton(
            self.frame_inputs,
            text="Загрузить список диалогов",
            width=200,
            command=self.load_dialogs_thread,
        )
        self.button_load_dialogs.grid(row=4, column=0, columnspan=2, padx=5, pady=(0, 10))

        # Скроллируемый фрейм для списка диалогов
        self.dialogs_frame = ctk.CTkScrollableFrame(self.frame_inputs, height=200, width=640)
        self.dialogs_frame.grid(row=5, column=0, columnspan=2, padx=5, pady=(0, 10), sticky="nsew")

        self.dialogs_checkboxes = []
        self.dialogs_data = []

        # ---------- Кнопки управления и прогресс ----------
        self.frame_controls = ctk.CTkFrame(self)
        self.frame_controls.pack(pady=(5, 10))

        self.button_export = ctk.CTkButton(
            self.frame_controls,
            text="Экспортировать выбранные диалоги",
            command=self.start_export_thread,
            width=250,
            # height=40,
        )
        self.button_export.grid(row=0, column=0, padx=(0, 10))
        self.button_export.configure(state="disabled")

        self.button_stop = ctk.CTkButton(
            self.frame_controls,
            text="Стоп",
            width=90,
            command=self.stop_export,
        )
        self.button_stop.grid(row=0, column=1, padx=(0, 0))
        self.button_stop.configure(state="disabled")

        self.label_progress_info = ctk.CTkLabel(
            self,
            text="Ожидание...",
            font=ctk.CTkFont(size=12),
        )
        self.label_progress_info.pack(pady=(5, 5))

        self.text_log = ctk.CTkTextbox(self, height=150)
        self.text_log.pack(fill="both", expand=True, padx=20, pady=(5, 15))
        self.text_log.insert("end", f"{APP_NAME} готов к работе.\n")
        self.text_log.configure(state="disabled")

        self.stop_flag = False
        self.vk_session = None
        self.vk = None

    # ===== Вспомогательные методы GUI =====

    def log(self, msg: str):
        self.text_log.configure(state="normal")
        self.text_log.insert("end", msg + "\n")
        self.text_log.see("end")
        self.text_log.configure(state="disabled")
        self.update_idletasks()

    def update_progress_label(self, text: str):
        self.label_progress_info.configure(text=text)
        self.update_idletasks()

    def open_token_page(self):
        webbrowser.open("https://vkhost.github.io", new=2)
        self.log("[INFO] Открыта страница для получения токена. Скопируйте всю ссылку после авторизации.")

    def stop_export(self):
        self.stop_flag = True
        self.update_progress_label("Остановка по запросу пользователя...")

    def load_dialogs_thread(self):
        t = threading.Thread(target=self.load_dialogs)
        t.daemon = True
        t.start()

    def start_export_thread(self):
        t = threading.Thread(target=self.export_dialogs)
        t.daemon = True
        t.start()

    # ===== Загрузка списка диалогов =====

    def load_dialogs(self):
        token_raw = self.entry_token.get().strip()
        token = extract_token(token_raw)

        if not token:
            self.log("[ERR] Не удалось извлечь access token. Вставьте токен или полную ссылку после авторизации.")
            self.update_progress_label("Ошибка: токен не найден")
            return

        self.config_data["last_token"] = token
        save_config(self.config_data)

        try:
            self.vk_session = vk_api.VkApi(token=token)
            self.vk = self.vk_session.get_api()
        except Exception as e:
            self.log(f"[ERR] Не удалось создать сессию VK: {e}")
            self.update_progress_label("Ошибка подключения к VK")
            return

        self.button_load_dialogs.configure(state="disabled")
        self.update_progress_label("Загрузка списка диалогов...")
        self.log("[INFO] Загружаю список диалогов...")

        try:
            # Очищаем предыдущий список
            for widget in self.dialogs_frame.winfo_children():
                widget.destroy()
            self.dialogs_checkboxes = []
            self.dialogs_data = []

            offset = 0
            count = 200
            total_loaded = 0

            while True:
                response = self.vk.messages.getConversations(offset=offset, count=count)
                items = response.get("items", [])

                if not items:
                    break

                for item in items:
                    conversation = item.get("conversation", {})
                    peer = conversation.get("peer", {})
                    peer_id = peer.get("id")
                    peer_type = peer.get("type")

                    last_message = item.get("last_message", {})
                    last_text = last_message.get("text", "")[:50]

                    if peer_type == "user":
                        user_info = get_user_info(self.vk, peer_id)
                        display_name = user_info["full_name"] or f"id{peer_id}"
                        dialog_type = "ЛС"
                    elif peer_type == "chat":
                        chat_id = peer_id - 2000000000
                        chat_info = get_chat_info(self.vk, chat_id)
                        display_name = chat_info["title"]
                        dialog_type = "Беседа"
                    elif peer_type == "group":
                        # Группа
                        group_id = abs(peer_id)
                        try:
                            group_info = self.vk.groups.getById(group_id=group_id)[0]
                            display_name = group_info.get("name", f"club{group_id}")
                        except:
                            display_name = f"club{group_id}"
                        dialog_type = "Группа"
                    else:
                        display_name = f"peer_id {peer_id}"
                        dialog_type = "Неизвестно"

                    label_text = f"[{dialog_type}] {display_name} (ID: {peer_id})"
                    if last_text:
                        label_text += f" - \"{last_text}...\""

                    var = ctk.StringVar(value="off")
                    checkbox = ctk.CTkCheckBox(
                        self.dialogs_frame,
                        text=label_text,
                        variable=var,
                        onvalue="on",
                        offvalue="off"
                    )
                    checkbox.pack(anchor="w", pady=2, padx=5)

                    self.dialogs_checkboxes.append(var)
                    self.dialogs_data.append({
                        "peer_id": peer_id,
                        "peer_type": peer_type,
                        "display_name": display_name,
                        "dialog_type": dialog_type
                    })

                total_loaded += len(items)
                self.update_progress_label(f"Загружено диалогов: {total_loaded}")

                offset += count
                time.sleep(DELAY)

            self.log(f"[INFO] Загружено {total_loaded} диалогов.")
            self.update_progress_label(f"Загружено {total_loaded} диалогов. Выберите нужные для экспорта.")
            self.button_export.configure(state="normal")

        except Exception as e:
            self.log(f"[ERR] Ошибка при загрузке диалогов: {e}")
            self.update_progress_label("Ошибка при загрузке")
        finally:
            self.button_load_dialogs.configure(state="normal")

    # ===== Экспорт диалогов =====

    def export_dialogs(self):
        if not self.vk:
            self.log("[ERR] Сначала загрузите список диалогов.")
            return

        # Получаем выбранные диалоги
        selected_dialogs = []
        for i, var in enumerate(self.dialogs_checkboxes):
            if var.get() == "on":
                selected_dialogs.append(self.dialogs_data[i])

        if not selected_dialogs:
            self.log("[WARN] Не выбрано ни одного диалога для экспорта.")
            self.update_progress_label("Выберите хотя бы один диалог")
            return

        self.stop_flag = False
        self.button_export.configure(state="disabled")
        self.button_stop.configure(state="normal")
        self.progress.set(0)

        export_dir = "exported_dialogs"
        ensure_dir(export_dir)

        self.log(f"[INFO] Начинаю экспорт {len(selected_dialogs)} диалогов...")

        try:
            for idx, dialog in enumerate(selected_dialogs):
                if self.stop_flag:
                    self.log("[INFO] Экспорт остановлен пользователем.")
                    break

                peer_id = dialog["peer_id"]
                display_name = dialog["display_name"]
                dialog_type = dialog["dialog_type"]

                safe_name = sanitize(display_name)
                filename = f"{safe_name}_id{peer_id}.md"
                filepath = os.path.join(export_dir, filename)

                self.log(f"[{idx + 1}/{len(selected_dialogs)}] Экспортирую: {display_name} (ID: {peer_id})")
                self.update_progress_label(f"Экспорт: {display_name} ({idx + 1}/{len(selected_dialogs)})")

                # Экспортируем диалог
                self.export_single_dialog(peer_id, filepath, display_name, dialog_type)

                # Обновляем прогресс
                progress_val = (idx + 1) / len(selected_dialogs)
                self.progress.set(progress_val)

            if not self.stop_flag:
                self.log(f"[INFO] Экспорт завершён! Файлы сохранены в папку: {export_dir}")
                self.update_progress_label(f"Готово! Экспортировано диалогов: {len(selected_dialogs)}")
                self.progress.set(1.0)
            else:
                self.update_progress_label("Экспорт остановлен пользователем")

        except Exception as e:
            self.log(f"[ERR] Ошибка при экспорте: {e}")
            self.update_progress_label("Ошибка при экспорте")
        finally:
            self.button_export.configure(state="normal")
            self.button_stop.configure(state="disabled")

    def export_single_dialog(self, peer_id: int, filepath: str, display_name: str, dialog_type: str):
        """Экспортирует один диалог в MD файл."""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                # Заголовок
                f.write(f"# Диалог: {display_name}\n\n")
                f.write(f"**Тип:** {dialog_type}\n")
                f.write(f"**Peer ID:** {peer_id}\n")
                f.write(f"**Дата экспорта:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("---\n\n")

                # Получаем сообщения
                offset = 0
                count = 200
                message_count = 0

                # Кеш для имен пользователей
                user_cache = {}

                while True:
                    if self.stop_flag:
                        break

                    response = self.vk.messages.getHistory(
                        peer_id=peer_id,
                        offset=offset,
                        count=count,
                        rev=1  # Сначала старые сообщения
                    )

                    items = response.get("items", [])
                    if not items:
                        break

                    for msg in items:
                        if self.stop_flag:
                            break

                        from_id = msg.get("from_id")
                        text = msg.get("text", "")
                        date = msg.get("date", 0)
                        attachments = msg.get("attachments", [])
                        reply_message = msg.get("reply_message")  # Информация об ответе

                        # Получаем имя отправителя
                        if from_id not in user_cache:
                            if from_id > 0:
                                user_info = get_user_info(self.vk, from_id)
                                user_cache[from_id] = user_info["full_name"] or f"id{from_id}"
                            else:
                                # Группа
                                group_id = abs(from_id)
                                try:
                                    group_info = self.vk.groups.getById(group_id=group_id)[0]
                                    user_cache[from_id] = group_info.get("name", f"club{group_id}")
                                except:
                                    user_cache[from_id] = f"club{group_id}"

                        sender_name = user_cache[from_id]
                        timestamp = format_timestamp(date)

                        # Записываем сообщение
                        f.write(f"## {sender_name}\n")
                        f.write(f"*{timestamp}*\n\n")

                        # Обработка ответа на сообщение
                        if reply_message:
                            reply_from_id = reply_message.get("from_id")
                            reply_text = reply_message.get("text", "")
                            reply_date = reply_message.get("date", 0)
                            reply_attachments = reply_message.get("attachments", [])

                            # Получаем имя автора цитируемого сообщения
                            if reply_from_id not in user_cache:
                                if reply_from_id > 0:
                                    reply_user_info = get_user_info(self.vk, reply_from_id)
                                    user_cache[reply_from_id] = reply_user_info["full_name"] or f"id{reply_from_id}"
                                else:
                                    reply_group_id = abs(reply_from_id)
                                    try:
                                        reply_group_info = self.vk.groups.getById(group_id=reply_group_id)[0]
                                        user_cache[reply_from_id] = reply_group_info.get("name", f"club{reply_group_id}")
                                    except:
                                        user_cache[reply_from_id] = f"club{reply_group_id}"

                            reply_sender_name = user_cache[reply_from_id]
                            reply_timestamp = format_timestamp(reply_date)

                            # Форматируем цитату
                            f.write(f"**↩️ В ответ на сообщение от {reply_sender_name}** *({reply_timestamp})*:\n")

                            if reply_text:
                                # Обрезаем длинный текст цитаты
                                quote_text = reply_text if len(reply_text) <= 200 else reply_text[:200] + "..."
                                # Форматируем как цитату (каждая строка с >)
                                quote_lines = quote_text.split('\n')
                                for line in quote_lines:
                                    f.write(f"> {line}\n")
                            else:
                                f.write("> *(без текста)*\n")

                            # Если в цитируемом сообщении были вложения
                            if reply_attachments:
                                att_types = [att.get("type", "unknown") for att in reply_attachments]
                                f.write(f"> *Вложения: {', '.join(att_types)}*\n")

                            f.write("\n")

                        # Основной текст сообщения
                        if text:
                            f.write(f"{text}\n\n")
                        else:
                            f.write("*(без текста)*\n\n")

                        # Информация о вложениях (без скачивания)
                        if attachments:
                            f.write("**Вложения:**\n")
                            for att in attachments:
                                att_type = att.get("type", "unknown")
                                f.write(f"- {att_type}\n")
                            f.write("\n")

                        f.write("---\n\n")
                        message_count += 1

                    offset += count
                    time.sleep(DELAY)

                self.log(f"  └─ Экспортировано сообщений: {message_count}")

        except Exception as e:
            self.log(f"[ERR] Ошибка при экспорте диалога {peer_id}: {e}")


if __name__ == "__main__":
    app = App()
    app.mainloop()


