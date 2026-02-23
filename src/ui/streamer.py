import asyncio
import html as html_lib
import logging
from telegram import Message, Chat
from telegram.constants import ParseMode
from telegram.error import RetryAfter, BadRequest

from src.config import TELEGRAM_MSG_LIMIT

logger = logging.getLogger(__name__)


class MessageSender:
    """
    Sends blocking (non-streaming) messages to Telegram.

    Design:
    - Tool events create separate permanent messages
    - "Working..." message shown at the top after user sends message
    - "Working..." deleted when final response is ready
    - Final response sent as new messages
    - Messages auto-split at 4000 chars with footer appended
    """

    PAGE_LIMIT = TELEGRAM_MSG_LIMIT  # Telegram's actual limit is 4096

    def __init__(self, message: Message):
        self.chat: Chat = message.chat
        self._working_msg: Message | None = None  # The "Working..." message to delete before final response
        self._stream_msg: Message | None = None   # Live-edited streaming message
        self._stream_buf: str = ""                # Accumulated streaming text
        self._stream_last_edit: float = 0.0       # Timestamp of last edit
        self._STREAM_DEBOUNCE = 1.0               # Minimum seconds between edits

    async def send_tool_event(self, detail: str):
        """Send a separate permanent message for each tool event."""
        await self._send_message(detail)
    
    async def create_working(self):
        """Create 'Working...' message once at the start."""
        if not self._working_msg:
            try:
                self._working_msg = await self._send_message_return("⏳ Working...")
            except Exception as e:
                logger.warning(f"Failed to create working message: {e}")

    async def delete_working(self):
        """Delete the 'Working...' message if it exists."""
        if self._working_msg:
            try:
                await asyncio.wait_for(self._working_msg.delete(), timeout=2.0)
            except Exception as e:
                logger.debug(f"Could not delete working message: {e}")
            finally:
                self._working_msg = None

    async def stream_delta(self, chunk: str):
        """Accumulate streaming delta and edit Telegram message at most once per second."""
        import time as _time
        self._stream_buf += chunk
        now = _time.monotonic()
        if now - self._stream_last_edit < self._STREAM_DEBOUNCE:
            return
        self._stream_last_edit = now

        preview = self._stream_buf
        if not self._stream_msg:
            # Replace "Working..." with the live message
            await self.delete_working()
            try:
                safe = html_lib.escape(preview) + " ✍️"
                self._stream_msg = await self.chat.send_message(safe, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.debug(f"Stream start failed: {e}")
        else:
            try:
                safe = html_lib.escape(preview) + " ✍️"
                await self._edit_message(self._stream_msg, safe)
            except Exception as e:
                logger.debug(f"Stream edit failed: {e}")

    async def finalize_stream(self, footer: str = ""):
        """Replace streaming message with the final content + footer."""
        if not self._stream_msg:
            return
        text = self._stream_buf
        if footer:
            text = text + "\n\n---\n" + footer
        try:
            safe = html_lib.escape(text)
            await self._edit_message(self._stream_msg, safe)
        except Exception:
            # If edit fails (e.g., message too long), fall back to sending new messages
            chunks = self._split_message(text)
            for chunk in chunks:
                await self._safe_send(html_lib.escape(chunk))
        finally:
            self._stream_msg = None
            self._stream_buf = ""

    async def send_response(self, text: str, footer: str = ""):
        """Send the final model response (with footer). Auto-splits long messages.
        
        Deletes "Working..." message first, then sends all response chunks as new messages.
        """
        await self.delete_working()
        
        # Build full response with footer
        full = text
        if footer:
            full = text + "\n\n---\n" + footer

        chunks = self._split_message(full)
        if not chunks:
            chunks = ["_(empty response)_"]

        # Send all chunks as new messages
        for chunk in chunks:
            safe = self._ensure_safe_markdown(chunk)
            await self._send_message(safe)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _split_message(self, text: str) -> list[str]:
        """Split text into chunks ≤ PAGE_LIMIT, closing/re-opening code blocks."""
        if len(text) <= self.PAGE_LIMIT:
            return [text]

        chunks: list[str] = []
        remaining = text
        in_code_block = False
        code_fence_lang = ""

        while remaining:
            if len(remaining) <= self.PAGE_LIMIT:
                chunks.append(remaining)
                break

            # Find a good break point near the limit
            limit = self.PAGE_LIMIT
            # Reserve space for closing a code block if needed
            if in_code_block:
                limit -= 5  # room for \n```

            cut = remaining[:limit]
            # Prefer breaking at double newline > newline > space
            break_at = cut.rfind("\n\n")
            if break_at < limit // 2:
                break_at = cut.rfind("\n")
            if break_at < limit // 2:
                break_at = cut.rfind(" ")
            if break_at < limit // 2:
                break_at = limit  # hard cut

            chunk = remaining[:break_at]
            remaining = remaining[break_at:].lstrip("\n")

            # Track code-block state: count triple-backtick occurrences in this chunk
            fences = chunk.split("```")
            # Number of ``` in chunk = len(fences) - 1
            fence_count = len(fences) - 1
            if fence_count % 2 != 0:
                in_code_block = not in_code_block
                # Find the language tag of the last opening fence if entering
                if in_code_block:
                    # Last fence piece is the content after the last ```
                    # The fence piece before it ends with the opening ``` line
                    last_fence_line = fences[-2].split("\n")[-1] if len(fences) >= 2 else ""
                    code_fence_lang = ""  # simplified — don't try to parse lang

            # Close unclosed code block at chunk boundary
            if in_code_block:
                chunk += "\n```"

            chunks.append(chunk)

            # Re-open code block in next chunk
            if in_code_block:
                remaining = f"```{code_fence_lang}\n" + remaining

        return chunks

    @staticmethod
    def _ensure_safe_markdown(text: str) -> str:
        """Close unclosed code blocks and inline code spans."""
        count = text.count("```")
        if count % 2 != 0:
            text += "\n```"
        if text.count("`") % 2 != 0 and "```" not in text[-5:]:
            text += "`"
        return text

    async def _edit_message(self, message: Message, text: str, _retry_count: int = 0):
        """Edit a Telegram message with markdown fallback."""
        try:
            await asyncio.wait_for(
                message.edit_text(text, parse_mode=ParseMode.MARKDOWN),
                timeout=10.0,
            )
        except RetryAfter as e:
            if _retry_count >= 3:
                logger.warning("⏱️ edit_message max retries reached — skipping")
                return
            await asyncio.sleep(e.retry_after)
            await self._edit_message(message, text, _retry_count + 1)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            elif "Can't parse entities" in str(e):
                try:
                    await asyncio.wait_for(
                        message.edit_text(html_lib.escape(text), parse_mode=ParseMode.HTML),
                        timeout=10.0,
                    )
                except Exception:
                    logger.warning("Failed to edit message even as plain text")
            else:
                logger.error(f"❌ edit_message failed: {e}")
        except asyncio.TimeoutError:
            logger.warning("⏱️ edit_message timeout — skipping")
        except Exception as e:
            logger.error(f"❌ edit_message error: {e}")

    async def _safe_send(self, text: str, _retry_count: int = 0) -> Message | None:
        """Core send logic with retry, markdown fallback, and error handling.

        Returns the sent Message (or None on failure / fire-and-forget).
        """
        try:
            return await asyncio.wait_for(
                self.chat.send_message(text, parse_mode=ParseMode.MARKDOWN),
                timeout=10.0,
            )
        except RetryAfter as e:
            if _retry_count >= 3:
                logger.warning("⏱️ send max retries reached — skipping")
                return None
            await asyncio.sleep(e.retry_after)
            return await self._safe_send(text, _retry_count + 1)
        except BadRequest as e:
            if "Can't parse entities" in str(e):
                try:
                    return await asyncio.wait_for(
                        self.chat.send_message(html_lib.escape(text), parse_mode=ParseMode.HTML),
                        timeout=10.0,
                    )
                except Exception:
                    logger.warning("Failed to send message even as plain text")
            else:
                logger.error(f"❌ send_message failed: {e}")
        except asyncio.TimeoutError:
            logger.warning("⏱️ send_message timeout — skipping")
        except Exception as e:
            logger.error(f"❌ send_message error: {e}")
        return None

    async def _send_message(self, text: str, _retry_count: int = 0):
        """Send a new message to the chat (fire-and-forget)."""
        await self._safe_send(text, _retry_count)

    async def _send_message_return(self, text: str, _retry_count: int = 0) -> Message | None:
        """Send a new message and return the Message object."""
        return await self._safe_send(text, _retry_count)
