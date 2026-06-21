"""
Splitwise MCP Server

This MCP server provides comprehensive Splitwise integration for Claude Desktop.
It allows you to manage expenses, friends, and groups through natural language.
"""

import warnings
warnings.filterwarnings("ignore")

import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
import requests
from mcp.server.fastmcp import FastMCP
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
REQUEST_TIMEOUT_SECONDS = int(os.getenv("SPLITWISE_REQUEST_TIMEOUT_SECONDS", "30"))


def _log(message: str) -> None:
    """Write diagnostics to stderr so stdout stays valid MCP JSON-RPC."""
    print(message, file=sys.stderr, flush=True)


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Set it in {PROJECT_ROOT / '.env'} or in your MCP client config."
        )
    return value


def _balance_amount(balance: Any) -> float:
    if hasattr(balance, "getAmount"):
        return float(balance.getAmount())
    return float(balance["amount"])


DOCUMENTED_ENDPOINTS = {
    "GET": {
        "/get_current_user",
        "/get_user/{id}",
        "/get_groups",
        "/get_group/{id}",
        "/get_friends",
        "/get_friend/{id}",
        "/get_currencies",
        "/get_expense/{id}",
        "/get_expenses",
        "/get_comments",
        "/get_notifications",
        "/get_categories",
    },
    "POST": {
        "/update_user/{id}",
        "/create_group",
        "/delete_group/{id}",
        "/undelete_group/{id}",
        "/add_user_to_group",
        "/remove_user_from_group",
        "/create_friend",
        "/create_friends",
        "/delete_friend/{id}",
        "/create_expense",
        "/update_expense/{id}",
        "/delete_expense/{id}",
        "/undelete_expense/{id}",
        "/create_comment",
        "/delete_comment/{id}",
    },
}


def _decimal_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return str(value)


def _api_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _compact_dict(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not data:
        return {}
    return {key: _api_value(value) for key, value in data.items() if value is not None}


def _flatten_indexed(prefix: str, items: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    if not items:
        return flat

    for index, item in enumerate(items):
        for key, value in item.items():
            if value is None:
                continue
            api_key = "user_id" if key == "id" else key
            flat[f"{prefix}__{index}__{api_key}"] = _api_value(value)

    return flat


def _validate_expense_shares(shares: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    if not shares:
        return None

    for index, share in enumerate(shares):
        has_existing_user = share.get("user_id") is not None or share.get("id") is not None
        has_new_user = bool(share.get("email") and share.get("first_name") and share.get("last_name"))
        if not has_existing_user and not has_new_user:
            return (
                f"shares[{index}] must identify a user with user_id/id, or with "
                "email, first_name, and last_name."
            )
        if share.get("paid_share") is None or share.get("owed_share") is None:
            return f"shares[{index}] must include paid_share and owed_share."

    return None


def _expand_endpoint(path_template: str, path_params: Optional[Dict[str, Any]] = None) -> str:
    path = path_template if path_template.startswith("/") else f"/{path_template}"
    for key, value in (path_params or {}).items():
        path = path.replace("{" + key + "}", str(value))
    return path


def _is_documented_endpoint(method: str, path: str) -> bool:
    method = method.upper()
    for template in DOCUMENTED_ENDPOINTS.get(method, set()):
        pattern = "^" + re.escape(template).replace(r"\{id\}", r"[^/]+") + "$"
        if re.match(pattern, path):
            return True
    return False


def _api_success(status_code: int, data: Any) -> bool:
    if not 200 <= status_code < 300:
        return False
    if isinstance(data, dict):
        errors = data.get("errors")
        if errors:
            return False
        if data.get("success") is False:
            return False
    return True


def _splitwise_api_request(
    method: str,
    endpoint: str,
    *,
    path_params: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    receipt_path: Optional[str] = None,
) -> Dict[str, Any]:
    method = method.upper()
    raw_endpoint = endpoint.strip()
    if raw_endpoint.startswith("http://") or raw_endpoint.startswith("https://") or ".." in raw_endpoint:
        return {
            "success": False,
            "error": "Endpoint must be a relative documented Splitwise API path.",
        }

    path = _expand_endpoint(endpoint, path_params)

    if "{" in path or "}" in path:
        return {
            "success": False,
            "error": f"Endpoint path parameter was not provided: {path}",
        }

    if not _is_documented_endpoint(method, path):
        return {
            "success": False,
            "error": f"{method} {path} is not in the documented Splitwise API endpoint list.",
            "documented_endpoints": sorted(DOCUMENTED_ENDPOINTS.get(method, set())),
        }

    headers = {
        "Authorization": f"Bearer {_get_required_env('SPLITWISE_API_KEY')}",
        "Accept": "application/json",
    }
    payload = _compact_dict(body)
    files = None
    receipt_handle = None

    try:
        if receipt_path:
            receipt = Path(receipt_path).expanduser()
            if not receipt.exists():
                return {
                    "success": False,
                    "error": f"Receipt file does not exist: {receipt}",
                }
            receipt_handle = receipt.open("rb")
            files = {"receipt": receipt_handle}

        response = requests.request(
            method,
            f"{SPLITWISE_API_BASE_URL}{path}",
            headers=headers,
            params=_compact_dict(query),
            data=payload if method == "POST" else None,
            files=files,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        try:
            data = response.json()
        except ValueError:
            data = response.text

        return {
            "success": _api_success(response.status_code, data),
            "status_code": response.status_code,
            "endpoint": path,
            "data": data,
            "errors": data.get("errors") if isinstance(data, dict) else None,
        }

    except requests.RequestException as e:
        return {
            "success": False,
            "endpoint": path,
            "error": str(e),
        }
    finally:
        if receipt_handle:
            receipt_handle.close()


def _create_or_update_expense_payload(
    *,
    description: Optional[str] = None,
    cost: Optional[Any] = None,
    group_id: Optional[int] = None,
    shares: Optional[List[Dict[str, Any]]] = None,
    split_equally: bool = False,
    currency_code: Optional[str] = None,
    date: Optional[str] = None,
    category_id: Optional[int] = None,
    details: Optional[str] = None,
    repeat_interval: Optional[str] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = _compact_dict(extra_fields)
    payload.update(_compact_dict({
        "description": description,
        "cost": _decimal_string(cost) if cost is not None else None,
        "group_id": group_id,
        "currency_code": currency_code,
        "date": date,
        "category_id": category_id,
        "details": details,
        "repeat_interval": repeat_interval,
    }))

    if split_equally:
        payload["split_equally"] = "true"
    if shares:
        payload.update(_flatten_indexed("users", shares))

    return payload


# Initialize Splitwise
sObj = Splitwise(
    _get_required_env("SPLITWISE_CONSUMER_KEY"),
    _get_required_env("SPLITWISE_CONSUMER_SECRET"),
    api_key=_get_required_env("SPLITWISE_API_KEY"),
)

# Create FastMCP server
mcp = FastMCP("Splitwise")

_log("Starting Splitwise MCP Server...")


# ============================================================================
# EXPENSE TOOLS
# ============================================================================

@mcp.tool()
def add_expense(
    description: str,
    amount: float,
    friend_name: str,
    payer: str = "me",
    split_type: str = "equal",
    my_share: Optional[float] = None,
    friend_share: Optional[float] = None,
    group_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add a new expense to Splitwise.

    Args:
        description: Description of the expense (e.g., "Dinner at restaurant")
        amount: Total amount of the expense
        friend_name: Name of the friend to split with (partial match works)
        payer: Who paid? "me" or "friend" (default: "me")
        split_type: How to split? "equal", "full", or "custom" (default: "equal")
            - equal: Split 50/50
            - full: Payer paid, other owes everything
            - custom: Use my_share and friend_share parameters
        my_share: Your share amount (only for custom split)
        friend_share: Friend's share amount (only for custom split)
        group_name: Optional group name to add expense to

    Returns:
        Dictionary with expense details and success status

    Examples:
        "Add expense for lunch $30 split with John"
        → add_expense("Lunch", 30, "John")

        "I paid $50 for dinner with Sarah, split equally"
        → add_expense("Dinner", 50, "Sarah", payer="me", split_type="equal")

        "John paid $40 for groceries, I owe it all"
        → add_expense("Groceries", 40, "John", payer="friend", split_type="full")
    """
    try:
        current = sObj.getCurrentUser()
        friends = sObj.getFriends()

        # Find friend by name
        friend_name_lower = friend_name.lower()
        matching_friends = [
            f for f in friends
            if friend_name_lower in f"{f.getFirstName()} {f.getLastName()}".lower()
        ]

        if not matching_friends:
            return {
                "success": False,
                "error": f"No friend found matching '{friend_name}'",
                "available_friends": [
                    f"{f.getFirstName()} {f.getLastName()}" for f in friends
                ]
            }

        selected_friend = matching_friends[0]

        # Determine payer
        if payer.lower() in ["me", "i", "myself"]:
            payer_id = current.getId()
            payer_name = current.getFirstName()
        else:
            payer_id = selected_friend.getId()
            payer_name = selected_friend.getFirstName()

        # Calculate shares
        if split_type == "equal":
            user1_share = amount / 2
            user2_share = amount / 2
        elif split_type == "full":
            if payer_id == current.getId():
                user1_share = 0.0
                user2_share = amount
            else:
                user1_share = amount
                user2_share = 0.0
        elif split_type == "custom":
            if my_share is None or friend_share is None:
                return {
                    "success": False,
                    "error": "For custom split, you must provide my_share and friend_share"
                }
            user1_share = my_share
            user2_share = friend_share
        else:
            return {
                "success": False,
                "error": f"Invalid split_type: {split_type}. Use 'equal', 'full', or 'custom'"
            }

        # Find group if specified
        group_id = None
        if group_name:
            groups = sObj.getGroups()
            matching_groups = [
                g for g in groups
                if group_name.lower() in g.getName().lower()
            ]
            if matching_groups:
                group_id = matching_groups[0].getId()

        # Create expense
        expense = Expense()
        expense.setCost(str(amount))
        expense.setDescription(description)

        if group_id:
            expense.setGroupId(group_id)

        # Create users
        user1 = ExpenseUser()
        user1.setId(current.getId())
        user1.setPaidShare(str(amount) if payer_id == current.getId() else '0.00')
        user1.setOwedShare(str(user1_share))

        user2 = ExpenseUser()
        user2.setId(selected_friend.getId())
        user2.setPaidShare(str(amount) if payer_id == selected_friend.getId() else '0.00')
        user2.setOwedShare(str(user2_share))

        expense.setUsers([user1, user2])

        # Submit expense
        created_expense, errors = sObj.createExpense(expense)

        if errors:
            return {
                "success": False,
                "error": str(errors)
            }

        return {
            "success": True,
            "expense_id": created_expense.getId(),
            "description": description,
            "amount": amount,
            "paid_by": payer_name,
            "your_share": user1_share,
            "friend_share": user2_share,
            "friend_name": f"{selected_friend.getFirstName()} {selected_friend.getLastName()}",
            "group": group_name if group_id else "Personal",
            "url": f"https://secure.splitwise.com/#/expenses/{created_expense.getId()}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def list_expenses(limit: int = 20) -> Dict[str, Any]:
    """
    List recent expenses from Splitwise.

    Args:
        limit: Maximum number of expenses to return (default: 20)

    Returns:
        Dictionary with list of expenses

    Example:
        "Show me my recent expenses"
        → list_expenses()
    """
    try:
        expenses = sObj.getExpenses(limit=limit)

        expense_list = []
        for expense in expenses:
            expense_list.append({
                "id": expense.getId(),
                "date": expense.getDate(),
                "description": expense.getDescription(),
                "amount": expense.getCost(),
                "paid_by": expense.getCreatedBy().getFirstName() if expense.getCreatedBy() else "Unknown"
            })

        return {
            "success": True,
            "count": len(expense_list),
            "expenses": expense_list
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_expense(expense_id: int) -> Dict[str, Any]:
    """
    Delete an expense from Splitwise.

    Args:
        expense_id: ID of the expense to delete

    Returns:
        Dictionary with success status

    Example:
        "Delete expense 123456"
        → delete_expense(123456)
    """
    result = _splitwise_api_request(
        "POST",
        "/delete_expense/{id}",
        path_params={"id": expense_id},
    )
    result["expense_id"] = expense_id
    result["message"] = (
        "Expense deleted successfully" if result["success"] else "Failed to delete expense"
    )
    return result


# ============================================================================
# FRIEND TOOLS
# ============================================================================

@mcp.tool()
def list_friends() -> Dict[str, Any]:
    """
    List all your Splitwise friends with balance information.

    Returns:
        Dictionary with list of friends and their balances

    Example:
        "Show me my friends"
        → list_friends()
    """
    try:
        current = sObj.getCurrentUser()
        friends = sObj.getFriends()

        friend_list = []
        for friend in friends:
            balance_info = ""
            balance_amount = 0.0

            balances = friend.getBalances()
            if balances:
                for bal in balances:
                    amount = _balance_amount(bal)
                    balance_amount = amount
                    if amount > 0:
                        balance_info = f"owes you ${amount:.2f}"
                    elif amount < 0:
                        balance_info = f"you owe ${abs(amount):.2f}"
                    else:
                        balance_info = "settled up"

            friend_list.append({
                "id": friend.getId(),
                "name": f"{friend.getFirstName()} {friend.getLastName()}",
                "email": friend.getEmail() if friend.getEmail() else "",
                "balance": balance_info,
                "balance_amount": balance_amount
            })

        return {
            "success": True,
            "current_user": f"{current.getFirstName()} {current.getLastName()}",
            "count": len(friend_list),
            "friends": friend_list
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def add_friend(email: str, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Add a new friend to Splitwise.

    Args:
        email: Friend's email address
        first_name: Friend's first name (optional)
        last_name: Friend's last name (optional)

    Returns:
        Dictionary with created friend details

    Example:
        "Add friend john@example.com"
        → add_friend("john@example.com", "John", "Doe")
    """
    return _splitwise_api_request(
        "POST",
        "/create_friend",
        body={
            "user_email": email,
            "user_first_name": first_name,
            "user_last_name": last_name,
        },
    )


@mcp.tool()
def delete_friend(friend_id: int) -> Dict[str, Any]:
    """
    Delete a friend from Splitwise.

    Args:
        friend_id: ID of the friend to delete

    Returns:
        Dictionary with success status

    Example:
        "Delete friend 79774"
        → delete_friend(79774)
    """
    result = _splitwise_api_request(
        "POST",
        "/delete_friend/{id}",
        path_params={"id": friend_id},
    )
    result["friend_id"] = friend_id
    result["message"] = (
        "Friend deleted successfully" if result["success"] else "Failed to delete friend"
    )
    return result


# ============================================================================
# GROUP TOOLS
# ============================================================================

@mcp.tool()
def list_groups() -> Dict[str, Any]:
    """
    List all your Splitwise groups.

    Returns:
        Dictionary with list of groups

    Example:
        "Show me my groups"
        → list_groups()
    """
    try:
        groups = sObj.getGroups()

        group_list = []
        for group in groups:
            # Get full group details to count members
            full_group = sObj.getGroup(group.getId())
            members = full_group.getMembers()

            group_list.append({
                "id": group.getId(),
                "name": group.getName(),
                "member_count": len(members),
                "members": [
                    f"{m.getFirstName()} {m.getLastName()}" for m in members
                ]
            })

        return {
            "success": True,
            "count": len(group_list),
            "groups": group_list
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def get_group_details(group_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific group.

    Args:
        group_name: Name of the group (partial match works)

    Returns:
        Dictionary with group details and members

    Example:
        "Show details for Roommates group"
        → get_group_details("Roommates")
    """
    try:
        groups = sObj.getGroups()

        group_name_lower = group_name.lower()
        matching_groups = [
            g for g in groups
            if group_name_lower in g.getName().lower()
        ]

        if not matching_groups:
            return {
                "success": False,
                "error": f"No group found matching '{group_name}'",
                "available_groups": [g.getName() for g in groups]
            }

        selected_group = matching_groups[0]
        full_group = sObj.getGroup(selected_group.getId())

        members = []
        for member in full_group.getMembers():
            members.append({
                "id": member.getId(),
                "name": f"{member.getFirstName()} {member.getLastName()}",
                "email": member.getEmail() if member.getEmail() else ""
            })

        return {
            "success": True,
            "group_id": full_group.getId(),
            "group_name": full_group.getName(),
            "member_count": len(members),
            "members": members
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def create_group(group_name: str, member_names: List[str]) -> Dict[str, Any]:
    """
    Create a new group on Splitwise.

    Args:
        group_name: Name for the new group
        member_names: List of friend names to add to the group (partial matches work)

    Returns:
        Dictionary with created group details

    Example:
        "Create group 'Weekend Trip' with John and Sarah"
        → create_group("Weekend Trip", ["John", "Sarah"])
    """
    try:
        friends = sObj.getFriends()

        # Find matching friends
        member_ids = []
        found_members = []

        for member_name in member_names:
            member_name_lower = member_name.lower()
            matching = [
                f for f in friends
                if member_name_lower in f"{f.getFirstName()} {f.getLastName()}".lower()
            ]

            if matching:
                friend = matching[0]
                member_ids.append(friend.getId())
                found_members.append(f"{friend.getFirstName()} {friend.getLastName()}")

        if not member_ids:
            return {
                "success": False,
                "error": "No matching friends found",
                "available_friends": [
                    f"{f.getFirstName()} {f.getLastName()}" for f in friends
                ]
            }

        response = _splitwise_api_request(
            "POST",
            "/create_group",
            body={
                "name": group_name,
                **_flatten_indexed(
                    "users",
                    [{"user_id": friend_id} for friend_id in member_ids],
                ),
            },
        )

        response.update({
            "members_added": found_members,
            "member_count": len(found_members),
        })
        return response

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def delete_group(group_id: int) -> Dict[str, Any]:
    """
    Delete a group from Splitwise.

    Args:
        group_id: ID of the group to delete

    Returns:
        Dictionary with success status

    Example:
        "Delete group 12345"
        → delete_group(12345)
    """
    result = _splitwise_api_request(
        "POST",
        "/delete_group/{id}",
        path_params={"id": group_id},
    )
    result["group_id"] = group_id
    result["message"] = (
        "Group deleted successfully" if result["success"] else "Failed to delete group"
    )
    return result


# ============================================================================
# FULL SPLITWISE API TOOLS
# ============================================================================

@mcp.tool()
def splitwise_api_capabilities() -> Dict[str, Any]:
    """
    Describe the documented Splitwise API endpoints exposed by this MCP server.

    Use this when you need to choose the right low-level tool or construct a
    full expense payload with arbitrary payers, owed shares, metadata, comments,
    group membership, notifications, currencies, or categories.
    """
    return {
        "success": True,
        "api_base_url": SPLITWISE_API_BASE_URL,
        "get_endpoints": sorted(DOCUMENTED_ENDPOINTS["GET"]),
        "post_endpoints": sorted(DOCUMENTED_ENDPOINTS["POST"]),
        "expense_create_modes": {
            "equal_group_split": {
                "required": ["description", "cost", "group_id", "split_equally=true"],
                "notes": "Only valid for group expenses. The authenticated user is the payer.",
            },
            "by_shares": {
                "required": ["description", "cost", "group_id", "shares"],
                "share_fields": [
                    "user_id or id",
                    "email + first_name + last_name",
                    "paid_share",
                    "owed_share",
                ],
                "notes": (
                    "Supports multiple participants, multiple payers, unequal splits, "
                    "payments, out-of-group expenses with group_id=0, category_id, "
                    "currency_code, date, details, repeat_interval, receipt_path, "
                    "and extra_fields for any documented/raw API field."
                ),
            },
        },
        "raw_tools": ["splitwise_api_get", "splitwise_api_post"],
    }


@mcp.tool()
def splitwise_api_get(
    endpoint: str,
    path_params: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Call any documented Splitwise GET endpoint.

    Args:
        endpoint: Documented endpoint path, e.g. "/get_user/{id}" or "/get_user/123".
        path_params: Values for path placeholders, e.g. {"id": 123}.
        query: Query string parameters for endpoints such as /get_expenses.
    """
    return _splitwise_api_request(
        "GET",
        endpoint,
        path_params=path_params,
        query=query,
    )


@mcp.tool()
def splitwise_api_post(
    endpoint: str,
    path_params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    receipt_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call any documented Splitwise POST endpoint.

    Args:
        endpoint: Documented endpoint path, e.g. "/update_expense/{id}" or "/delete_group/123".
        path_params: Values for path placeholders, e.g. {"id": 123}.
        body: Request body fields. For user arrays, use flattened keys or a higher-level tool.
        receipt_path: Optional local receipt file path for expense create/update.
    """
    return _splitwise_api_request(
        "POST",
        endpoint,
        path_params=path_params,
        body=body,
        receipt_path=receipt_path,
    )


@mcp.tool()
def get_current_user() -> Dict[str, Any]:
    """Get the authenticated Splitwise user."""
    return _splitwise_api_request("GET", "/get_current_user")


@mcp.tool()
def get_user(user_id: int) -> Dict[str, Any]:
    """Get another Splitwise user by ID."""
    return _splitwise_api_request(
        "GET",
        "/get_user/{id}",
        path_params={"id": user_id},
    )


@mcp.tool()
def update_user(user_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update user profile fields.

    Supported documented fields include first_name, last_name, email, password,
    locale, and default_currency.
    """
    return _splitwise_api_request(
        "POST",
        "/update_user/{id}",
        path_params={"id": user_id},
        body=fields,
    )


@mcp.tool()
def get_groups() -> Dict[str, Any]:
    """List the current user's groups with full raw API data."""
    return _splitwise_api_request("GET", "/get_groups")


@mcp.tool()
def get_group(group_id: int) -> Dict[str, Any]:
    """Get full details for a group by ID."""
    return _splitwise_api_request(
        "GET",
        "/get_group/{id}",
        path_params={"id": group_id},
    )


@mcp.tool()
def create_group_full(
    name: str,
    group_type: Optional[str] = None,
    simplify_by_default: Optional[bool] = None,
    members: Optional[List[Dict[str, Any]]] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a Splitwise group using the documented API.

    Args:
        name: Group name.
        group_type: home, trip, couple, other, apartment, or house.
        simplify_by_default: Whether to simplify debts by default.
        members: Optional users to add. Each item may include user_id/id, or email
            plus first_name/last_name.
        extra_fields: Additional raw API fields.
    """
    body = _compact_dict(extra_fields)
    body.update(_compact_dict({
        "name": name,
        "group_type": group_type,
        "simplify_by_default": simplify_by_default,
    }))
    body.update(_flatten_indexed("users", members))

    return _splitwise_api_request("POST", "/create_group", body=body)


@mcp.tool()
def undelete_group(group_id: int) -> Dict[str, Any]:
    """Restore a deleted group by ID."""
    return _splitwise_api_request(
        "POST",
        "/undelete_group/{id}",
        path_params={"id": group_id},
    )


@mcp.tool()
def add_user_to_group(
    group_id: int,
    user_id: Optional[int] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """Add an existing user or invite a user by email/name to a group."""
    if user_id is None and not (first_name and last_name and email):
        return {
            "success": False,
            "error": "Provide either user_id or first_name, last_name, and email.",
        }

    return _splitwise_api_request(
        "POST",
        "/add_user_to_group",
        body={
            "group_id": group_id,
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
        },
    )


@mcp.tool()
def remove_user_from_group(group_id: int, user_id: int) -> Dict[str, Any]:
    """Remove a user from a group. Splitwise rejects non-zero balances."""
    return _splitwise_api_request(
        "POST",
        "/remove_user_from_group",
        body={"group_id": group_id, "user_id": user_id},
    )


@mcp.tool()
def get_friends() -> Dict[str, Any]:
    """List the current user's friends with full raw API data."""
    return _splitwise_api_request("GET", "/get_friends")


@mcp.tool()
def get_friend(friend_id: int) -> Dict[str, Any]:
    """Get details about a friend by ID."""
    return _splitwise_api_request(
        "GET",
        "/get_friend/{id}",
        path_params={"id": friend_id},
    )


@mcp.tool()
def create_friend(
    email: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a friend through the documented API."""
    return add_friend(email=email, first_name=first_name, last_name=last_name)


@mcp.tool()
def create_friends(users: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Add multiple friends at once.

    Each user should include email, and first_name when the user does not
    already exist.
    """
    return _splitwise_api_request(
        "POST",
        "/create_friends",
        body=_flatten_indexed("users", users),
    )


@mcp.tool()
def get_currencies() -> Dict[str, Any]:
    """List Splitwise-supported currencies."""
    return _splitwise_api_request("GET", "/get_currencies")


@mcp.tool()
def get_categories() -> Dict[str, Any]:
    """List Splitwise-supported expense categories."""
    return _splitwise_api_request("GET", "/get_categories")


@mcp.tool()
def get_expense(expense_id: int) -> Dict[str, Any]:
    """Get full expense details by ID."""
    return _splitwise_api_request(
        "GET",
        "/get_expense/{id}",
        path_params={"id": expense_id},
    )


@mcp.tool()
def get_expenses(
    group_id: Optional[int] = None,
    friend_id: Optional[int] = None,
    dated_after: Optional[str] = None,
    dated_before: Optional[str] = None,
    updated_after: Optional[str] = None,
    updated_before: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List expenses with all documented filters and full raw API data."""
    return _splitwise_api_request(
        "GET",
        "/get_expenses",
        query={
            "group_id": group_id,
            "friend_id": friend_id,
            "dated_after": dated_after,
            "dated_before": dated_before,
            "updated_after": updated_after,
            "updated_before": updated_before,
            "limit": limit,
            "offset": offset,
        },
    )


@mcp.tool()
def create_expense_full(
    description: str,
    cost: str,
    group_id: int = 0,
    shares: Optional[List[Dict[str, Any]]] = None,
    split_equally: bool = False,
    currency_code: Optional[str] = None,
    date: Optional[str] = None,
    category_id: Optional[int] = None,
    details: Optional[str] = None,
    repeat_interval: Optional[str] = None,
    receipt_path: Optional[str] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create any documented Splitwise expense shape.

    For equal group split, set split_equally=true and group_id to a real group.
    For all other expense/share modes, pass shares like:
    [{"user_id": 1, "paid_share": "30.00", "owed_share": "10.00"},
     {"user_id": 2, "paid_share": "0.00", "owed_share": "20.00"}]

    This supports multiple participants, multiple payers, unequal/custom splits,
    payments via extra_fields, currency, date, category, notes, recurring fields,
    out-of-group expenses with group_id=0, and optional receipt upload.
    """
    if split_equally and shares:
        return {
            "success": False,
            "error": "Use either split_equally or shares, not both.",
        }
    if split_equally and group_id == 0:
        return {
            "success": False,
            "error": "split_equally requires a non-zero group_id.",
        }
    if not split_equally and not shares:
        return {
            "success": False,
            "error": "Provide shares, or use split_equally=true with a group_id.",
        }

    share_error = _validate_expense_shares(shares)
    if share_error:
        return {"success": False, "error": share_error}

    return _splitwise_api_request(
        "POST",
        "/create_expense",
        body=_create_or_update_expense_payload(
            description=description,
            cost=cost,
            group_id=group_id,
            shares=shares,
            split_equally=split_equally,
            currency_code=currency_code,
            date=date,
            category_id=category_id,
            details=details,
            repeat_interval=repeat_interval,
            extra_fields=extra_fields,
        ),
        receipt_path=receipt_path,
    )


@mcp.tool()
def update_expense_full(
    expense_id: int,
    description: Optional[str] = None,
    cost: Optional[str] = None,
    group_id: Optional[int] = None,
    shares: Optional[List[Dict[str, Any]]] = None,
    currency_code: Optional[str] = None,
    date: Optional[str] = None,
    category_id: Optional[int] = None,
    details: Optional[str] = None,
    repeat_interval: Optional[str] = None,
    receipt_path: Optional[str] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Update an expense using documented create_expense-style fields.

    If shares are supplied, Splitwise overwrites all shares for the expense with
    the supplied share list.
    """
    share_error = _validate_expense_shares(shares)
    if share_error:
        return {"success": False, "error": share_error}

    return _splitwise_api_request(
        "POST",
        "/update_expense/{id}",
        path_params={"id": expense_id},
        body=_create_or_update_expense_payload(
            description=description,
            cost=cost,
            group_id=group_id,
            shares=shares,
            currency_code=currency_code,
            date=date,
            category_id=category_id,
            details=details,
            repeat_interval=repeat_interval,
            extra_fields=extra_fields,
        ),
        receipt_path=receipt_path,
    )


@mcp.tool()
def undelete_expense(expense_id: int) -> Dict[str, Any]:
    """Restore a deleted expense by ID."""
    return _splitwise_api_request(
        "POST",
        "/undelete_expense/{id}",
        path_params={"id": expense_id},
    )


@mcp.tool()
def get_comments(expense_id: int) -> Dict[str, Any]:
    """Get comments for an expense."""
    return _splitwise_api_request(
        "GET",
        "/get_comments",
        query={"expense_id": expense_id},
    )


@mcp.tool()
def create_comment(expense_id: int, content: str) -> Dict[str, Any]:
    """Create a comment on an expense."""
    return _splitwise_api_request(
        "POST",
        "/create_comment",
        body={"expense_id": expense_id, "content": content},
    )


@mcp.tool()
def delete_comment(comment_id: int) -> Dict[str, Any]:
    """Delete a comment by ID."""
    return _splitwise_api_request(
        "POST",
        "/delete_comment/{id}",
        path_params={"id": comment_id},
    )


@mcp.tool()
def get_notifications() -> Dict[str, Any]:
    """Get Splitwise notifications for the current user."""
    return _splitwise_api_request("GET", "/get_notifications")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point for the MCP server."""
    _log("\n" + "="*60)
    _log("SPLITWISE MCP SERVER")
    _log("="*60)
    _log("\nConvenience tools and full documented Splitwise API tools registered.")
    _log("\nReady to accept requests from Claude Desktop.")
    _log("="*60 + "\n")

    # Run the MCP server
    mcp.run()


if __name__ == "__main__":
    main()
