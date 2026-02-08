import asyncio
import logging
from telegram import Message, Chat
from telegram.constants import ParseMode
from telegram.error import RetryAfter, BadRequest

logger = logging.getLogger(__name__)


class MessageSender:
    """
    Sends blocking (non-streaming) messages to Telegram.

    Design:
    - The initial "Thinking..." placeholder is edited into the first real content
      (tool event or final response), so there's no leftover placeholder.
    - Each tool event is a separate, permanent message (never overwritten).
    - The final model response is sent as one or more messages (auto-split at 4000 chars)
      with a footer appended after a --- separator.
    """

    PAGE_LIMIT = 4000  # Safe margin below Telegram's 4096

    def __init__(self, message: Message):
        self.placeholder = message          # The "Thinking..." message
        self.chat: Chat = message.chat
        self._placeholder_used = False      # Has placeholder been edited yet?

    async def send_tool_event(self, detail: str):
        """Send a permanent tool-use message. First call edits the placeholder."""
        # Detail already contains emoji prefix from formatters
        text = detail
        if not self._placeholder_used:
            self._placeholder_used = True
            await self._edit_message(self.placeholder, text)
        else:
            await self._send_message(text)

    async def send_response(self, text: str, footer: str = ""):
        """Send the final model response (with footer). Auto-splits long messages."""
        full = text
        if footer:
            full = text + "\n\n---\n" + footer

        chunks = self._split_message(full)
        if not chunks:
            chunks = ["_(empty response)_"]

        for i, chunk in enumerate(chunks):
            safe = self._ensure_safe_markdown(chunk)
            if i == 0 and not self._placeholder_used:
                # Edit the "Thinking..." placeholder into the first chunk
                self._placeholder_used = True
                await self._edit_message(self.placeholder, safe)
            else:
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
                    await asyncio.wait_for(message.edit_text(text), timeout=10.0)
                except Exception:
                    logger.warning("Failed to edit message even as plain text")
            else:
                logger.error(f"❌ edit_message failed: {e}")
        except asyncio.TimeoutError:
            logger.warning("⏱️ edit_message timeout — skipping")
        except Exception as e:
            logger.error(f"❌ edit_message error: {e}")

    async def _send_message(self, text: str, _retry_count: int = 0):
        """Send a new message to the chat with markdown fallback."""
        try:
            await asyncio.wait_for(
                self.chat.send_message(text, parse_mode=ParseMode.MARKDOWN),
                timeout=10.0,
            )
        except RetryAfter as e:
            if _retry_count >= 3:
                logger.warning("⏱️ send_message max retries reached — skipping")
                return
            await asyncio.sleep(e.retry_after)
            await self._send_message(text, _retry_count + 1)
        except BadRequest as e:
            if "Can't parse entities" in str(e):
                try:
                    await asyncio.wait_for(self.chat.send_message(text), timeout=10.0)
                except Exception:
                    logger.warning("Failed to send message even as plain text")
            else:
                logger.error(f"❌ send_message failed: {e}")
        except asyncio.TimeoutError:
            logger.warning("⏱️ send_message timeout — skipping")
        except Exception as e:
            logger.error(f"❌ send_message error: {e}")
