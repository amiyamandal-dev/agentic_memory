from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langchain_deepseek import ChatDeepSeek
from langmem import create_manage_memory_tool, create_search_memory_tool
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage
import json
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
from enum import Enum


class MemoryImportance(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class MemoryType(Enum):
    PREFERENCE = "preference"
    FACT = "fact"
    INTERACTION = "interaction"
    SKILL = "skill"
    ERROR = "error"


# Enhanced Experience model with memory management fields
class Experience(BaseModel):
    observation: str
    reasoning: str
    action: str
    outcome: Dict[str, Any]

    # Memory management fields
    importance: MemoryImportance = Field(default=MemoryImportance.MEDIUM)
    memory_type: MemoryType = Field(default=MemoryType.INTERACTION)
    created_at: datetime = Field(default_factory=datetime.now)
    last_accessed: datetime = Field(default_factory=datetime.now)
    access_count: int = Field(default=1)
    decay_factor: float = Field(default=1.0)  # Higher = more persistent
    tags: List[str] = Field(default_factory=list)
    related_memories: List[str] = Field(default_factory=list)


class ForgetPolicy:
    """Implements various forgetting strategies for memory management"""

    def __init__(self, max_memories: int = 1000):
        self.max_memories = max_memories

    def should_forget(self, memory: Experience, current_time: datetime) -> bool:
        """Determine if a memory should be forgotten based on multiple criteria"""

        # Never forget critical memories
        if memory.importance == MemoryImportance.CRITICAL:
            return False

        # Time-based decay
        age_days = (current_time - memory.created_at).days
        time_threshold = self._get_time_threshold(memory.importance)

        if age_days > time_threshold:
            return True

        # Access-based forgetting (memories accessed less frequently are forgotten)
        recency_days = (current_time - memory.last_accessed).days
        if recency_days > 30 and memory.access_count < 3:
            return True

        # Error memories can be forgotten sooner if they're old
        if memory.memory_type == MemoryType.ERROR and age_days > 7:
            return True

        return False

    def _get_time_threshold(self, importance: MemoryImportance) -> int:
        """Get retention time in days based on importance"""
        thresholds = {
            MemoryImportance.LOW: 7,  # 1 week
            MemoryImportance.MEDIUM: 30,  # 1 month
            MemoryImportance.HIGH: 90,  # 3 months
            MemoryImportance.CRITICAL: 365  # 1 year (but never actually forgotten)
        }
        return thresholds.get(importance, 30)

    def select_memories_to_forget(self, memories: List[Experience],
                                  current_time: datetime,
                                  target_count: Optional[int] = None) -> List[Experience]:
        """Select memories to forget when approaching memory limits"""

        if target_count is None:
            target_count = max(0, len(memories) - self.max_memories)

        if target_count <= 0:
            return []

        # Score memories for forgetting (higher score = more likely to forget)
        scored_memories = []
        for memory in memories:
            if memory.importance == MemoryImportance.CRITICAL:
                continue  # Never forget critical memories

            score = self._calculate_forget_score(memory, current_time)
            scored_memories.append((score, memory))

        # Sort by score (highest first) and select top candidates
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        return [memory for score, memory in scored_memories[:target_count]]

    def _calculate_forget_score(self, memory: Experience, current_time: datetime) -> float:
        """Calculate a score indicating how suitable a memory is for forgetting"""
        score = 0.0

        # Age factor
        age_days = (current_time - memory.created_at).days
        score += age_days * 0.1

        # Recency factor
        recency_days = (current_time - memory.last_accessed).days
        score += recency_days * 0.2

        # Importance factor (inverse)
        importance_penalty = {
            MemoryImportance.LOW: 0,
            MemoryImportance.MEDIUM: -10,
            MemoryImportance.HIGH: -25,
            MemoryImportance.CRITICAL: -1000
        }
        score += importance_penalty.get(memory.importance, 0)

        # Access frequency factor (inverse)
        score -= memory.access_count * 2

        # Memory type factor
        if memory.memory_type == MemoryType.ERROR:
            score += 5  # Errors are more forgettable
        elif memory.memory_type == MemoryType.PREFERENCE:
            score -= 10  # Preferences are less forgettable

        return score


class SummaryPolicy:
    """Implements memory summarization to compress old memories"""

    def __init__(self, model, summary_threshold_days: int = 14):
        self.model = model
        self.summary_threshold_days = summary_threshold_days

    def should_summarize(self, memories: List[Experience], current_time: datetime) -> bool:
        """Determine if memories should be summarized"""

        # Check if we have enough old memories to summarize
        old_memories = [
            m for m in memories
            if (current_time - m.created_at).days > self.summary_threshold_days
        ]

        return len(old_memories) > 10  # Summarize if we have more than 10 old memories

    def create_summary(self, memories: List[Experience], config: Dict) -> Experience:
        """Create a summary of multiple memories"""

        # Group memories by type and importance
        grouped_memories = self._group_memories(memories)

        # Generate summary content
        summary_content = self._generate_summary_content(grouped_memories)

        # Create summary experience
        summary = Experience(
            observation=f"Summary of {len(memories)} memories",
            reasoning="Consolidated multiple memories to reduce storage and improve retrieval",
            action="memory_summarization",
            outcome={
                "original_memory_count": len(memories),
                "summary_created_at": datetime.now().isoformat(),
                "memory_types_included": list(grouped_memories.keys()),
                "summary_content": summary_content
            },
            importance=MemoryImportance.HIGH,
            memory_type=MemoryType.FACT,
            tags=["summary", "consolidated"],
            related_memories=[f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}"]
        )

        return summary

    def _group_memories(self, memories: List[Experience]) -> Dict[str, List[Experience]]:
        """Group memories by type for organized summarization"""
        groups = {}
        for memory in memories:
            key = memory.memory_type.value
            if key not in groups:
                groups[key] = []
            groups[key].append(memory)
        return groups

    def _generate_summary_content(self, grouped_memories: Dict[str, List[Experience]]) -> str:
        """Generate human-readable summary content"""
        summary_parts = []

        for memory_type, memories in grouped_memories.items():
            if not memories:
                continue

            count = len(memories)
            summary_parts.append(f"\n{memory_type.title()} Memories ({count}):")

            # Extract key patterns and themes
            if memory_type == "preference":
                preferences = [m.observation for m in memories[:5]]  # Top 5
                summary_parts.append(f"Key preferences: {', '.join(preferences)}")

            elif memory_type == "interaction":
                recent_interactions = sorted(memories, key=lambda x: x.created_at, reverse=True)[:3]
                summary_parts.append(
                    f"Recent interactions focused on: {', '.join([m.action for m in recent_interactions])}")

            elif memory_type == "skill":
                skills = [m.observation for m in memories]
                summary_parts.append(f"Demonstrated skills: {', '.join(skills)}")

        return "\n".join(summary_parts)


class AdvancedMemoryManager:
    """Enhanced memory manager with forget and summary policies"""

    def __init__(self, manage_tool, search_tool, model,
                 max_memories: int = 1000,
                 summary_threshold_days: int = 14):
        self.manage_tool = manage_tool
        self.search_tool = search_tool
        self.model = model

        self.forget_policy = ForgetPolicy(max_memories)
        self.summary_policy = SummaryPolicy(model, summary_threshold_days)

        self.memory_count = 0
        self.last_maintenance = datetime.now()

    def store_experience(self, observation: str, reasoning: str, action: str,
                         outcome: Dict[str, Any], config: Dict,
                         importance: MemoryImportance = MemoryImportance.MEDIUM,
                         memory_type: MemoryType = MemoryType.INTERACTION,
                         tags: List[str] = None) -> bool:
        """Store experience with enhanced metadata"""

        try:
            # Ensure outcome is JSON serializable
            json.dumps(outcome)

            experience = Experience(
                observation=observation,
                reasoning=reasoning,
                action=action,
                outcome=outcome,
                importance=importance,
                memory_type=memory_type,
                tags=tags or []
            )

            # Store the memory
            self.manage_tool.invoke({
                "content": experience,
                "action": "create"
            }, config=config)

            self.memory_count += 1

            # Trigger maintenance if needed
            self._maybe_run_maintenance(config)

            return True

        except Exception as e:
            print(f"Failed to store experience: {e}")
            return False

    def _maybe_run_maintenance(self, config: Dict):
        """Run memory maintenance if conditions are met"""

        current_time = datetime.now()

        # Run maintenance every hour or when memory limit is approached
        if (current_time - self.last_maintenance).seconds > 3600 or \
                self.memory_count > self.forget_policy.max_memories * 0.9:
            print("🧹 Running memory maintenance...")
            self._run_memory_maintenance(config)
            self.last_maintenance = current_time

    def _run_memory_maintenance(self, config: Dict):
        """Execute forget and summary policies"""

        try:
            # Get all memories (this would need to be implemented based on your memory retrieval system)
            # For now, we'll simulate this
            all_memories = self._get_all_memories(config)

            current_time = datetime.now()

            # Apply forget policy
            memories_to_forget = self.forget_policy.select_memories_to_forget(
                all_memories, current_time
            )

            if memories_to_forget:
                print(f"🗑️  Forgetting {len(memories_to_forget)} old/irrelevant memories")
                for memory in memories_to_forget:
                    self._delete_memory(memory, config)

            # Apply summary policy
            remaining_memories = [m for m in all_memories if m not in memories_to_forget]

            if self.summary_policy.should_summarize(remaining_memories, current_time):
                print("📋 Creating memory summary...")

                # Find memories to summarize (old, low-importance ones)
                summarizable_memories = [
                    m for m in remaining_memories
                    if (current_time - m.created_at).days > self.summary_policy.summary_threshold_days
                       and m.importance != MemoryImportance.CRITICAL
                ]

                if len(summarizable_memories) > 5:
                    summary = self.summary_policy.create_summary(summarizable_memories, config)
                    self.store_experience(
                        summary.observation,
                        summary.reasoning,
                        summary.action,
                        summary.outcome,
                        config,
                        importance=MemoryImportance.HIGH,
                        memory_type=MemoryType.FACT,
                        tags=["summary"]
                    )

                    # Remove summarized memories
                    for memory in summarizable_memories:
                        self._delete_memory(memory, config)

            print("✅ Memory maintenance completed")

        except Exception as e:
            print(f"❌ Memory maintenance failed: {e}")

    def _get_all_memories(self, config: Dict) -> List[Experience]:
        """Retrieve all memories from storage"""
        # This is a placeholder - you'd need to implement based on your storage system
        # For now, return empty list
        return []

    def _delete_memory(self, memory: Experience, config: Dict):
        """Delete a specific memory"""
        try:
            # This would need to be implemented based on your storage system
            # For now, just log the action
            print(f"Deleting memory: {memory.observation[:50]}...")
        except Exception as e:
            print(f"Failed to delete memory: {e}")

    def search_memories(self, query: str, config: Dict,
                        memory_type: Optional[MemoryType] = None,
                        min_importance: Optional[MemoryImportance] = None) -> List[Experience]:
        """Enhanced memory search with filtering"""

        try:
            # Use the search tool
            results = self.search_tool.invoke({"query": query}, config=config)

            # Apply filters if specified
            filtered_results = results
            if memory_type:
                filtered_results = [r for r in filtered_results if getattr(r, 'memory_type', None) == memory_type]

            if min_importance:
                filtered_results = [r for r in filtered_results if
                                    getattr(r, 'importance', MemoryImportance.LOW).value >= min_importance.value]

            # Update access information for retrieved memories
            for memory in filtered_results:
                if hasattr(memory, 'last_accessed'):
                    memory.last_accessed = datetime.now()
                if hasattr(memory, 'access_count'):
                    memory.access_count += 1

            return filtered_results

        except Exception as e:
            print(f"Memory search failed: {e}")
            return []


# Updated main execution code
def setup_database():
    """Initialize the required database tables"""
    try:
        print("Setting up database...")
        with PostgresStore.from_conn_string(DB_URI) as temp_store:
            temp_store.setup()

        with PostgresSaver.from_conn_string(DB_URI) as temp_saver:
            temp_saver.setup()

        print("✅ Database tables initialized successfully")
        return True

    except Exception as e:
        print(f"Database setup failed: {e}")
        return False


def run_agent_with_advanced_memory(agent, initial_state, config, memory_manager):
    """Run agent with advanced memory management"""
    conversation_history = []

    try:
        for event in agent.stream(initial_state, config=config):
            print(event)
            for key, value in event.items():
                if key == "messages" and value:
                    for message in value:
                        if isinstance(message, (AIMessage, HumanMessage, BaseMessage)):
                            content = str(message.content)
                            message_type = message.__class__.__name__

                            print(f"{message_type}: {content}")

                            conversation_history.append({
                                "content": content,
                                "type": message_type,
                                "timestamp": datetime.now().isoformat()
                            })

        # Store conversation with appropriate classification
        if conversation_history:
            # Determine importance and type based on content
            importance = MemoryImportance.MEDIUM
            memory_type = MemoryType.INTERACTION

            # Simple heuristics for classification
            content_lower = ' '.join([msg["content"].lower() for msg in conversation_history])

            if any(word in content_lower for word in ["remember", "important", "preference", "like", "dislike"]):
                importance = MemoryImportance.HIGH
                memory_type = MemoryType.PREFERENCE
            elif any(word in content_lower for word in ["error", "mistake", "wrong", "failed"]):
                memory_type = MemoryType.ERROR
            elif any(word in content_lower for word in ["learn", "skill", "how to", "tutorial"]):
                memory_type = MemoryType.SKILL
                importance = MemoryImportance.HIGH

            memory_manager.store_experience(
                observation=f"Processed conversation about {initial_state['messages'][0].get('content', 'unknown topic')[:100]}",
                reasoning="Agent successfully handled user interaction",
                action="Generated appropriate responses",
                outcome={
                    "message_count": len(conversation_history),
                    "conversation_length": sum(len(msg["content"]) for msg in conversation_history),
                    "model_used": "deepseek-chat",
                    "status": "success",
                    "session_id": config.get("configurable", {}).get("thread_id", "unknown")
                },
                config=config,
                importance=importance,
                memory_type=memory_type,
                tags=["conversation", "interaction"]
            )

    except Exception as e:
        print(f"Error during agent execution: {e}")
        memory_manager.store_experience(
            observation="Agent execution encountered an error",
            reasoning=f"Error type: {type(e).__name__}",
            action="Attempted to handle error gracefully",
            outcome={
                "error_message": str(e),
                "status": "error",
                "recovered": True
            },
            config=config,
            importance=MemoryImportance.MEDIUM,
            memory_type=MemoryType.ERROR,
            tags=["error", "recovery"]
        )


# Updated main execution
DB_URI = "postgresql://postgres:password@localhost:5432/agentic_memory"

if __name__ == "__main__":
    if not setup_database():
        print("Exiting due to database setup failure...")
        exit(1)

    with PostgresStore.from_conn_string(DB_URI) as memory_store, \
            PostgresSaver.from_conn_string(DB_URI) as convo_ckpt:

        manage_tool = create_manage_memory_tool(
            namespace=("episodes", "{thread_id}"),
            schema=Experience,
            instructions="Proactively call this tool when you:\n\n1. Identify a new USER preference.\n2. Receive an explicit USER request to remember something.\n3. Learn something important about the user.\n4. Need to correct outdated information.\n",
            actions_permitted=("create", "update", "delete")
        )

        search_tool = create_search_memory_tool(
            namespace=("episodes", "{thread_id}")
        )

        model = ChatDeepSeek(
            model="deepseek-chat",
            temperature=0.0,
            api_key=""
        )

        # Create advanced memory manager
        memory_manager = AdvancedMemoryManager(
            manage_tool,
            search_tool,
            model,
            max_memories=1000,  # Adjust based on your needs
            summary_threshold_days=14
        )

        tools = [manage_tool, search_tool]

        agent = create_react_agent(
            model,
            tools=tools,
            checkpointer=convo_ckpt,
            store=memory_store
        )

        config = {"configurable": {"thread_id": "batman"}}
        initial_state = {"messages": [{"role": "user",
                                       "content": "whats my name? and whats ,my preferences?",}]}

        print("🚀 Starting Advanced LangGraph Memory Bot...")
        print("🧠 Advanced memory management with forget and summary policies enabled")
        print("📊 PostgreSQL memory storage with intelligent cleanup")
        print("-" * 50)

        run_agent_with_advanced_memory(agent, initial_state, config, memory_manager)


    print("-" * 50)
    print("✅ Conversation completed with advanced memory management!")