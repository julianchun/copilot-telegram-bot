import time
import asyncio
from telegram import Message
from telegram.constants import ParseMode
from telegram.error import RetryAfter, BadRequest

class SmartStreamer:
    """
    Handles streaming text to Telegram with debouncing, buffering, and markdown safety.
    Also handles status updates (e.g. "Reading file...").
    """
    def __init__(self, message: Message, update_interval: float = 0.5, chunk_size: int = 50):
        self.message = message
        self.update_interval = update_interval
        self.chunk_size = chunk_size
        self.full_text = ""
        self.current_status = ""
        self.last_update_time = 0.0
        self.last_update_text_len = 0
        self.cursor = " ▋"
        self._running = True
        
        # Pagination handling
        self.messages = [message]
        self.page_limit = 4000  # Safe limit below 4096

    async def update_status(self, status: str):
        """
        Updates the status line (prepend/header) without waiting for text chunks.
        """
        self.current_status = status
        await self._update_message(force=True)

    async def stream(self, new_text_chunk: str):
        """
        Accumulates text and updates the message if enough time/text has passed.
        """
        # Clear status once we start receiving real answer text
        if self.current_status and new_text_chunk.strip():
            self.current_status = ""
            
        self.full_text += new_text_chunk
        
        current_time = time.time()
        time_diff = current_time - self.last_update_time
        char_diff = len(self.full_text) - self.last_update_text_len

        if time_diff >= self.update_interval or char_diff >= self.chunk_size:
            await self._update_message()

    async def close(self):
        """
        Final update with the complete text and no cursor.
        """
        self._running = False
        self.current_status = "" # Clear status on finish
        await self._update_message(final=True)

    def _ensure_safe_markdown(self, text: str, force_close: bool = False) -> str:
        """
        Checks for unclosed code blocks and other markdown entities.
        """
        # 1. Handle code blocks
        count = text.count("```")
        if count % 2 != 0:
            text += "\n```"
        
        # 2. Handle inline code `
        # Only check if not inside a code block (simple heuristic)
        # We can just count all backticks. If odd, close it.
        # But ``` uses 3, so we need to be careful. 
        # Actually, simpler approach for stability:
        # If the text ends with an odd number of backticks/stars/underscores, 
        # it might be incomplete.
        
        # Simple heuristic: If the text ends with a partial entity marker, 
        # or has an unclosed pair, Telegram dies.
        # A robust way is complex, but a simple way for streaming is:
        # If the last character is a special markdown char, remove it temporarily 
        # (it will come in the next chunk).
        
        if text and text[-1] in ('*', '_', '`', '['):
            # Don't show the very last char if it's a potential opener/closer
            # This avoids "bold start" errors like "Text **"
            text = text[:-1]

        return text

    async def log_event(self, log_text: str):
        """
        Inserts a log message ABOVE the current streaming message.
        It does this by deleting the current streaming message(s),
        sending the log, and then creating a new streaming message.
        """
        # 1. Delete current streaming messages
        for msg in self.messages:
            try:
                await msg.delete()
            except Exception:
                pass # Message might already be gone or too old
        
        self.messages = [] # Reset message tracking

        # 2. Send the log message
        # Use simple printing for the log
        try:
            # We use the chat_id from the original message to send the log
            # The original message object (self.message) might be stale if we deleted it,
            # but the chat object attached to it usually works. 
            # Safer to use the chat_id.
            chat = self.message.chat
            await chat.send_message(log_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            print(f"Failed to send log: {e}")

        # 3. Re-create the streaming message
        # We need to resend the content we have so far (self.full_text)
        # plus the cursor.
        
        # If we have no text yet, just send the cursor or "Thinking..." equivalent?
        # Ideally we restore exactly what was there.
        text_to_restore = self.full_text
        if not text_to_restore:
            text_to_restore = " " # Space to allow sending
        
        # We rely on _update_message to handle the splitting and sending.
        # But _update_message assumes self.messages has at least one item.
        # So we must create the first one.
        try:
            new_msg = await chat.send_message("`Restoring stream...`", parse_mode=ParseMode.MARKDOWN)
            self.messages = [new_msg]
            # Force an update to render the full text correctly immediately
            await self._update_message(force=True)
        except Exception as e:
             print(f"Failed to restore stream: {e}")

    async def _update_message(self, final: bool = False, force: bool = False):
        """
        Updates the Telegram message(s), handling pagination.
        """
        # If we have a status, it goes on the last message
        # If we have text, it's appended.
        
        total_len = len(self.full_text)
        page_index = total_len // self.page_limit
        
        # Ensure we have enough messages
        while len(self.messages) <= page_index:
            # Finalize previous
            prev_msg = self.messages[-1]
            prev_page_idx = len(self.messages) - 1
            prev_start = prev_page_idx * self.page_limit
            prev_end = (prev_page_idx + 1) * self.page_limit
            prev_text = self.full_text[prev_start:prev_end]
            
            try:
                safe_prev = self._ensure_safe_markdown(prev_text, force_close=True)
                await prev_msg.edit_text(safe_prev, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
            
            # Send new message
            new_msg = await self.messages[-1].reply_text(self.cursor)
            self.messages.append(new_msg)

        # Update current message
        current_msg = self.messages[page_index]
        start_idx = page_index * self.page_limit
        current_chunk = self.full_text[start_idx:]
        
        # Compose display text
        display_text = current_chunk
        
        # Prepend status if exists and we are on the last page
        if self.current_status:
             display_text = f"_{self.current_status}_\n\n" + display_text

        if not final:
            display_text += self.cursor

        safe_text = self._ensure_safe_markdown(display_text)
        
        # If empty (no text, no status), skip unless final (to remove cursor)
        if not safe_text.strip() and not final:
            return

        try:
            await current_msg.edit_text(safe_text, parse_mode=ParseMode.MARKDOWN)
            self.last_update_time = time.time()
            self.last_update_text_len = len(self.full_text)
                
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await self._update_message(final, force)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            elif "Can't parse entities" in str(e):
                # If markdown fails, fallback to sending WITHOUT parse_mode temporarily
                # or just wait for next chunk. 
                # Better: try to strip the last few chars which might be causing it
                try:
                    # Fallback: Plain text (safest)
                    await current_msg.edit_text(display_text)
                except Exception:
                    pass
            else:
                print(f"Failed to update message: {e}")
        except Exception as e:
            print(f"Stream update error: {e}")