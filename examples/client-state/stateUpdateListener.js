trame.state.addListener(({ type, keys }) => {
    if (type === "dirty-state" && keys.includes("msg")) {
        trame.state.set("change_count", trame.state.get("change_count") + 1);
    }
});