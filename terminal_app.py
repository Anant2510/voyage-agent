from agent import VoyageAgent
from cache import cache_stats, clear_cache


def print_banner():
    print("\n" + "=" * 60)
    print("  V O Y A G E   C O N C I E R G E   A G E N T")
    print("=" * 60)
    print("  Your AI-powered travel planner")
    print("  Commands: 'quit' | 'reset' | 'cache stats' | 'cache clear'")
    print("=" * 60 + "\n")


def show_cache_stats():
    """Display current cache statistics."""
    stats = cache_stats()
    print("\n" + "─" * 50)
    print("📊 CACHE STATS")
    print("─" * 50)
    print(f"  Total entries:    {stats['total_entries']}")
    print(f"  Total size:       {stats['total_size_kb']} KB")
    print(f"  Expired entries:  {stats['expired_entries']}")
    if stats['by_tool']:
        print(f"  Breakdown by tool:")
        for tool, count in stats['by_tool'].items():
            print(f"    • {tool}: {count}")
    else:
        print("  (Cache is empty)")
    print("─" * 50 + "\n")


def main():
    print_banner()
    
    try:
        agent = VoyageAgent()
    except ValueError as e:
        print(f"Setup Error: {e}")
        print("Make sure your .env file has ANTHROPIC_API_KEY set correctly.")
        return
    
    print("Voyage: Hi! I'm Voyage, your travel concierge. Where would you like to go?\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nSafe travels! Goodbye!\n")
            break
        
        if not user_input:
            continue
        
        # System commands
        if user_input.lower() in ["quit", "exit", "bye"]:
            print("\nSafe travels! Goodbye!\n")
            break
        
        if user_input.lower() == "reset":
            agent.reset()
            print("\nStarting fresh! Where to next?\n")
            continue
        
        if user_input.lower() == "cache stats":
            show_cache_stats()
            continue
        
        if user_input.lower() == "cache clear":
            count = clear_cache()
            print(f"\n🗑️  Cleared {count} cached entries.\n")
            continue
        
        # Regular conversation
        try:
            print()
            response = agent.chat(user_input)
            print(f"\nVoyage: {response}\n")
        except Exception as e:
            print(f"\nError: {e}")
            print("Try asking again or type 'reset' to start over.\n")


if __name__ == "__main__":
    main()