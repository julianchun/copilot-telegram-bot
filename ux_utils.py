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
        self.chat = message.chat # Store chat for recovering stream
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

    # ... (log_event, update_status, stream, close, ensure_safe_markdown stay same) ...

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
            if not self.messages:
                # Recover from empty state (e.g. after log_event)
                try:
                    new_msg = await self.chat.send_message(self.cursor)
                    self.messages.append(new_msg)
                    continue
                except Exception as e:
                    print(f"Failed to recover stream: {e}")
                    return

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