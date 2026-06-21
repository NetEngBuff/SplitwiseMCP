import warnings
warnings.filterwarnings("ignore")

import os
from pathlib import Path
from dotenv import load_dotenv
import requests
from splitwise import Splitwise
from splitwise.expense import Expense
from splitwise.user import ExpenseUser, User
from splitwise.group import Group

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(APP_DIR / ".env")
SPLITWISE_API_BASE_URL = os.getenv(
    "SPLITWISE_API_BASE_URL",
    "https://secure.splitwise.com/api/v3.0",
).rstrip("/")


def get_required_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Set it in {PROJECT_ROOT / '.env'}."
        )
    return value


def balance_amount(balance):
    if hasattr(balance, "getAmount"):
        return float(balance.getAmount())
    return float(balance["amount"])


def api_value(value):
    if isinstance(value, bool):
        return str(value).lower()
    return value


def compact_dict(data):
    return {key: api_value(value) for key, value in data.items() if value is not None}


def splitwise_api_post(endpoint, body=None):
    response = requests.post(
        f"{SPLITWISE_API_BASE_URL}{endpoint}",
        headers={
            "Authorization": f"Bearer {get_required_env('SPLITWISE_API_KEY')}",
            "Accept": "application/json",
        },
        data=compact_dict(body or {}),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def api_response_success(data):
    return not data.get("errors") and data.get("success", True) is not False


def flatten_user_ids(user_ids):
    return {
        f"users__{index}__user_id": user_id
        for index, user_id in enumerate(user_ids)
    }


# Initialize Splitwise
sObj = Splitwise(
    get_required_env("SPLITWISE_CONSUMER_KEY"),
    get_required_env("SPLITWISE_CONSUMER_SECRET"),
    api_key=get_required_env("SPLITWISE_API_KEY"),
)

def refresh_data():
    """Refresh friends and groups from server"""
    global current, friends, groups
    current = sObj.getCurrentUser()
    friends = sObj.getFriends()
    groups = sObj.getGroups()

refresh_data()

print("="*60)
print(f"🎯 SPLITWISE MANAGER")
print("="*60)
print(f"Logged in as: {current.getFirstName()} {current.getLastName()} (ID: {current.getId()})")
print("="*60)


def find_friend_by_name(name_query):
    """Find a friend by name (partial match)"""
    matches = []
    name_query = name_query.lower()
    for friend in friends:
        full_name = f"{friend.getFirstName()} {friend.getLastName()}".lower()
        if name_query in full_name:
            matches.append(friend)
    return matches


def find_common_groups(friend_id):
    """Find groups that both current user and friend are in"""
    common_groups = []
    for group in groups:
        members = sObj.getGroup(group.getId()).getMembers()
        member_ids = [m.getId() for m in members]
        if current.getId() in member_ids and friend_id in member_ids:
            common_groups.append(group)
    return common_groups


def add_expense_interactive():
    """Interactive expense creation"""

    # Step 1: Get expense description and amount
    print("\n" + "="*60)
    print("ADD NEW EXPENSE")
    print("="*60)

    description = input("\nExpense description: ").strip()
    if not description:
        print("Error: Description cannot be empty!")
        return

    try:
        total_amount = float(input("Total amount: $").strip())
        if total_amount <= 0:
            print("Error: Amount must be positive!")
            return
    except ValueError:
        print("Error: Invalid amount!")
        return

    # Step 2: Find the friend
    print("\n" + "-"*60)
    friend_name = input("Enter friend's name (or part of it): ").strip()
    matches = find_friend_by_name(friend_name)

    if not matches:
        print(f"\nNo friends found matching '{friend_name}'")
        print("\nAvailable friends:")
        for friend in friends:
            print(f"  - {friend.getFirstName()} {friend.getLastName()}")
        return

    if len(matches) == 1:
        selected_friend = matches[0]
        print(f"\nFound: {selected_friend.getFirstName()} {selected_friend.getLastName()}")
    else:
        print(f"\nMultiple matches found:")
        for i, friend in enumerate(matches, 1):
            print(f"  {i}. {friend.getFirstName()} {friend.getLastName()}")
        try:
            choice = int(input("\nSelect friend (number): ").strip())
            if 1 <= choice <= len(matches):
                selected_friend = matches[choice - 1]
            else:
                print("Invalid choice!")
                return
        except ValueError:
            print("Invalid input!")
            return

    # Step 3: Check for common groups
    print("\n" + "-"*60)
    common_groups = find_common_groups(selected_friend.getId())

    group_id = None
    if common_groups:
        print(f"\nYou and {selected_friend.getFirstName()} are in these groups:")
        for i, group in enumerate(common_groups, 1):
            print(f"  {i}. {group.getName()}")
        print(f"  {len(common_groups) + 1}. No group (personal expense)")

        try:
            choice = int(input("\nAdd expense to which group? (number): ").strip())
            if 1 <= choice <= len(common_groups):
                group_id = common_groups[choice - 1].getId()
                print(f"Adding to group: {common_groups[choice - 1].getName()}")
            elif choice == len(common_groups) + 1:
                print("Adding as personal expense")
            else:
                print("Invalid choice!")
                return
        except ValueError:
            print("Invalid input!")
            return
    else:
        print(f"\nNo common groups with {selected_friend.getFirstName()}. Adding as personal expense.")

    # Step 4: Who paid?
    print("\n" + "-"*60)
    print("Who paid for this expense?")
    print(f"  1. {current.getFirstName()} (You)")
    print(f"  2. {selected_friend.getFirstName()}")

    try:
        payer_choice = int(input("\nEnter choice (1 or 2): ").strip())
        if payer_choice == 1:
            payer_id = current.getId()
            payer_name = current.getFirstName()
        elif payer_choice == 2:
            payer_id = selected_friend.getId()
            payer_name = selected_friend.getFirstName()
        else:
            print("Invalid choice!")
            return
    except ValueError:
        print("Invalid input!")
        return

    # Step 5: How to split?
    print("\n" + "-"*60)
    print("How should this be split?")
    print(f"  1. Split equally (${total_amount/2:.2f} each)")
    print(f"  2. {payer_name} paid, other person owes everything")
    print(f"  3. Custom split")

    try:
        split_choice = int(input("\nEnter choice (1, 2, or 3): ").strip())

        if split_choice == 1:
            # Split equally
            user1_share = total_amount / 2
            user2_share = total_amount / 2
        elif split_choice == 2:
            # Payer paid, other owes all
            if payer_choice == 1:
                user1_share = 0.0
                user2_share = total_amount
            else:
                user1_share = total_amount
                user2_share = 0.0
        elif split_choice == 3:
            # Custom split
            user1_share = float(input(f"\nHow much should {current.getFirstName()} owe? $").strip())
            user2_share = float(input(f"How much should {selected_friend.getFirstName()} owe? $").strip())

            if abs((user1_share + user2_share) - total_amount) > 0.01:
                print(f"\nWarning: Shares (${user1_share + user2_share:.2f}) don't add up to total (${total_amount:.2f})")
                confirm = input("Continue anyway? (y/n): ").strip().lower()
                if confirm != 'y':
                    return
        else:
            print("Invalid choice!")
            return
    except ValueError:
        print("Invalid input!")
        return

    # Step 6: Confirmation
    print("\n" + "="*60)
    print("EXPENSE SUMMARY")
    print("="*60)
    print(f"Description: {description}")
    print(f"Total Amount: ${total_amount:.2f}")
    print(f"Paid by: {payer_name}")
    print(f"{current.getFirstName()} owes: ${user1_share:.2f}")
    print(f"{selected_friend.getFirstName()} owes: ${user2_share:.2f}")
    if group_id:
        group_name = next(g.getName() for g in common_groups if g.getId() == group_id)
        print(f"Group: {group_name}")
    else:
        print("Group: Personal expense")
    print("="*60)

    confirm = input("\nCreate this expense? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Expense cancelled.")
        return

    # Step 7: Create the expense
    expense = Expense()
    expense.setCost(str(total_amount))
    expense.setDescription(description)

    if group_id:
        expense.setGroupId(group_id)

    # Create user 1 (current user)
    user1 = ExpenseUser()
    user1.setId(current.getId())
    user1.setPaidShare(str(total_amount) if payer_id == current.getId() else '0.00')
    user1.setOwedShare(str(user1_share))

    # Create user 2 (friend)
    user2 = ExpenseUser()
    user2.setId(selected_friend.getId())
    user2.setPaidShare(str(total_amount) if payer_id == selected_friend.getId() else '0.00')
    user2.setOwedShare(str(user2_share))

    users = [user1, user2]
    expense.setUsers(users)

    # Create the expense
    print("\nCreating expense...")
    expense, errors = sObj.createExpense(expense)

    if errors:
        print(f"\n❌ Error creating expense: {errors}")
    else:
        print(f"\n✅ Expense created successfully! ID: {expense.getId()}")
        print(f"View at: https://secure.splitwise.com/#/expenses/{expense.getId()}")


def list_friends():
    """List all friends"""
    print("\n" + "="*60)
    print("YOUR FRIENDS")
    print("="*60)
    if not friends:
        print("No friends found.")
        return

    for friend in friends:
        balance = friend.getBalances()
        balance_str = ""
        if balance:
            for bal in balance:
                amount = balance_amount(bal)
                if amount > 0:
                    balance_str = f" (owes you ${amount:.2f})"
                elif amount < 0:
                    balance_str = f" (you owe ${abs(amount):.2f})"
                else:
                    balance_str = " (settled up)"

        print(f"  {friend.getFirstName()} {friend.getLastName()} - ID: {friend.getId()}{balance_str}")


def add_friend():
    """Add a new friend"""
    print("\n" + "="*60)
    print("ADD FRIEND")
    print("="*60)

    email = input("\nEnter friend's email address: ").strip()
    if not email:
        print("Error: Email cannot be empty!")
        return

    first_name = input("Enter friend's first name (optional): ").strip()
    last_name = input("Enter friend's last name (optional): ").strip()

    try:
        result = splitwise_api_post("/create_friend", {
            "user_email": email,
            "user_first_name": first_name,
            "user_last_name": last_name,
        })
        if api_response_success(result):
            created_friend = result.get("friend", {})
            print(f"\n✅ Friend added successfully!")
            print(f"   {created_friend.get('first_name', '')} {created_friend.get('last_name', '')} (ID: {created_friend.get('id')})")
            refresh_data()
        else:
            print(f"\n❌ Failed to add friend: {result.get('errors')}")
    except Exception as e:
        print(f"\n❌ Error adding friend: {e}")


def delete_friend():
    """Delete a friend"""
    print("\n" + "="*60)
    print("DELETE FRIEND")
    print("="*60)

    if not friends:
        print("No friends to delete.")
        return

    print("\nYour friends:")
    for i, friend in enumerate(friends, 1):
        print(f"  {i}. {friend.getFirstName()} {friend.getLastName()} (ID: {friend.getId()})")

    try:
        choice = int(input("\nSelect friend to delete (number): ").strip())
        if 1 <= choice <= len(friends):
            selected_friend = friends[choice - 1]

            confirm = input(f"\nAre you sure you want to delete {selected_friend.getFirstName()} {selected_friend.getLastName()}? (y/n): ").strip().lower()
            if confirm == 'y':
                result = splitwise_api_post(f"/delete_friend/{selected_friend.getId()}")
                if api_response_success(result):
                    print(f"\n✅ Friend deleted successfully!")
                    refresh_data()
                else:
                    print(f"\n❌ Failed to delete friend: {result.get('errors')}")
        else:
            print("Invalid choice!")
    except ValueError:
        print("Invalid input!")
    except Exception as e:
        print(f"\n❌ Error: {e}")


def list_groups():
    """List all groups"""
    print("\n" + "="*60)
    print("YOUR GROUPS")
    print("="*60)
    if not groups:
        print("No groups found.")
        return

    for group in groups:
        members_count = len(sObj.getGroup(group.getId()).getMembers()) if group.getId() else 0
        print(f"  {group.getName()} - ID: {group.getId()} ({members_count} members)")


def view_group_details():
    """View detailed information about a group"""
    print("\n" + "="*60)
    print("GROUP DETAILS")
    print("="*60)

    if not groups:
        print("No groups available.")
        return

    print("\nYour groups:")
    for i, group in enumerate(groups, 1):
        print(f"  {i}. {group.getName()}")

    try:
        choice = int(input("\nSelect group to view (number): ").strip())
        if 1 <= choice <= len(groups):
            selected_group = groups[choice - 1]
            full_group = sObj.getGroup(selected_group.getId())

            print(f"\n{'='*60}")
            print(f"Group: {full_group.getName()}")
            print(f"ID: {full_group.getId()}")
            print(f"{'='*60}")
            print("\nMembers:")
            for member in full_group.getMembers():
                print(f"  - {member.getFirstName()} {member.getLastName()} (ID: {member.getId()})")
        else:
            print("Invalid choice!")
    except ValueError:
        print("Invalid input!")
    except Exception as e:
        print(f"\n❌ Error: {e}")


def create_group():
    """Create a new group"""
    print("\n" + "="*60)
    print("CREATE GROUP")
    print("="*60)

    group_name = input("\nEnter group name: ").strip()
    if not group_name:
        print("Error: Group name cannot be empty!")
        return

    print("\nAdd members to the group:")
    print("Available friends:")
    for i, friend in enumerate(friends, 1):
        print(f"  {i}. {friend.getFirstName()} {friend.getLastName()}")

    member_ids = []
    while True:
        choice = input("\nEnter friend number to add (or 'done' to finish): ").strip().lower()
        if choice == 'done':
            break

        try:
            idx = int(choice)
            if 1 <= idx <= len(friends):
                friend_id = friends[idx - 1].getId()
                if friend_id not in member_ids:
                    member_ids.append(friend_id)
                    print(f"  ✓ Added {friends[idx - 1].getFirstName()} {friends[idx - 1].getLastName()}")
                else:
                    print("  Already added!")
            else:
                print("Invalid choice!")
        except ValueError:
            print("Invalid input!")

    if not member_ids:
        print("\nNo members selected. Group not created.")
        return

    try:
        result = splitwise_api_post("/create_group", {
            "name": group_name,
            **flatten_user_ids(member_ids),
        })
        if api_response_success(result):
            created_group = result.get("group", {})
            print(f"\n✅ Group created successfully!")
            print(f"   {created_group.get('name')} (ID: {created_group.get('id')})")
            refresh_data()
        else:
            print(f"\n❌ Failed to create group: {result.get('errors')}")
    except Exception as e:
        print(f"\n❌ Error creating group: {e}")


def delete_group():
    """Delete a group"""
    print("\n" + "="*60)
    print("DELETE GROUP")
    print("="*60)

    if not groups:
        print("No groups to delete.")
        return

    print("\nYour groups:")
    for i, group in enumerate(groups, 1):
        print(f"  {i}. {group.getName()} (ID: {group.getId()})")

    try:
        choice = int(input("\nSelect group to delete (number): ").strip())
        if 1 <= choice <= len(groups):
            selected_group = groups[choice - 1]

            confirm = input(f"\nAre you sure you want to delete '{selected_group.getName()}'? (y/n): ").strip().lower()
            if confirm == 'y':
                result = splitwise_api_post(f"/delete_group/{selected_group.getId()}")
                if api_response_success(result):
                    print(f"\n✅ Group deleted successfully!")
                    refresh_data()
                else:
                    print(f"\n❌ Failed to delete group: {result.get('errors')}")
        else:
            print("Invalid choice!")
    except ValueError:
        print("Invalid input!")
    except Exception as e:
        print(f"\n❌ Error: {e}")


def list_expenses():
    """List recent expenses"""
    print("\n" + "="*60)
    print("RECENT EXPENSES")
    print("="*60)

    try:
        expenses = sObj.getExpenses(limit=20)

        if not expenses:
            print("No expenses found.")
            return

        for expense in expenses:
            date = expense.getDate()
            desc = expense.getDescription()
            cost = expense.getCost()
            paid_by = expense.getCreatedBy().getFirstName() if expense.getCreatedBy() else "Unknown"

            print(f"\n  ID: {expense.getId()}")
            print(f"  Date: {date}")
            print(f"  Description: {desc}")
            print(f"  Amount: ${cost}")
            print(f"  Paid by: {paid_by}")
            print(f"  {'-'*50}")

    except Exception as e:
        print(f"\n❌ Error: {e}")


def delete_expense():
    """Delete an expense"""
    print("\n" + "="*60)
    print("DELETE EXPENSE")
    print("="*60)

    try:
        expenses = sObj.getExpenses(limit=20)

        if not expenses:
            print("No expenses found.")
            return

        print("\nRecent expenses:")
        for i, expense in enumerate(expenses, 1):
            print(f"  {i}. {expense.getDescription()} - ${expense.getCost()} (ID: {expense.getId()})")

        choice = int(input("\nSelect expense to delete (number): ").strip())
        if 1 <= choice <= len(expenses):
            selected_expense = expenses[choice - 1]

            confirm = input(f"\nAre you sure you want to delete '{selected_expense.getDescription()}'? (y/n): ").strip().lower()
            if confirm == 'y':
                result = splitwise_api_post(f"/delete_expense/{selected_expense.getId()}")
                if api_response_success(result):
                    print(f"\n✅ Expense deleted successfully!")
                else:
                    print(f"\n❌ Failed to delete expense: {result.get('errors')}")
        else:
            print("Invalid choice!")

    except ValueError:
        print("Invalid input!")
    except Exception as e:
        print(f"\n❌ Error: {e}")


def interactive_prompt():
    """Main interactive prompt that responds to natural language"""
    print("\n" + "="*60)
    print("What would you like to do?")
    print("="*60)
    print("You can say things like:")
    print("  - 'add expense' or 'create expense'")
    print("  - 'show expenses' or 'list expenses'")
    print("  - 'delete expense'")
    print("  - 'show friends' or 'list friends'")
    print("  - 'add friend'")
    print("  - 'remove friend' or 'delete friend'")
    print("  - 'show groups' or 'list groups'")
    print("  - 'view group' or 'group details'")
    print("  - 'create group' or 'new group'")
    print("  - 'delete group' or 'remove group'")
    print("  - 'exit' or 'quit'")
    print("="*60)

    command = input("\n> ").strip().lower()

    # Expense commands
    if any(word in command for word in ['add expense', 'create expense', 'new expense']):
        return 'add_expense'
    elif any(word in command for word in ['show expense', 'list expense', 'view expense', 'see expense', 'display expense']):
        return 'list_expenses'
    elif any(word in command for word in ['delete expense', 'remove expense']):
        return 'delete_expense'

    # Friend commands
    elif any(word in command for word in ['show friend', 'list friend', 'view friend', 'see friend', 'display friend']):
        return 'list_friends'
    elif any(word in command for word in ['add friend', 'new friend', 'create friend']):
        return 'add_friend'
    elif any(word in command for word in ['delete friend', 'remove friend']):
        return 'delete_friend'

    # Group commands
    elif any(word in command for word in ['show group', 'list group', 'view group', 'see group', 'display group']) and 'detail' not in command:
        return 'list_groups'
    elif any(word in command for word in ['group detail', 'view group detail', 'show group detail']):
        return 'view_group_details'
    elif any(word in command for word in ['create group', 'new group', 'add group']):
        return 'create_group'
    elif any(word in command for word in ['delete group', 'remove group']):
        return 'delete_group'

    # Exit commands
    elif any(word in command for word in ['exit', 'quit', 'bye', 'goodbye']):
        return 'exit'

    else:
        print("\n❌ I didn't understand that command. Please try again.")
        return None


# Main program
if __name__ == "__main__":
    print("\n💬 Welcome to Interactive Splitwise Manager!")
    print("Just tell me what you want to do in plain English.")

    while True:
        action = interactive_prompt()

        if action == 'add_expense':
            add_expense_interactive()
        elif action == 'list_expenses':
            list_expenses()
        elif action == 'delete_expense':
            delete_expense()
        elif action == 'list_friends':
            list_friends()
        elif action == 'add_friend':
            add_friend()
        elif action == 'delete_friend':
            delete_friend()
        elif action == 'list_groups':
            list_groups()
        elif action == 'view_group_details':
            view_group_details()
        elif action == 'create_group':
            create_group()
        elif action == 'delete_group':
            delete_group()
        elif action == 'exit':
            print("\n👋 Goodbye!")
            break
        elif action is None:
            continue

        if action and action != 'exit':
            input("\n✓ Press Enter to continue...")
            refresh_data()
