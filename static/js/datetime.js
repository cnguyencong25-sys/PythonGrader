(function (global) {
  const vietnamTimeZone = "Asia/Ho_Chi_Minh";

  global.parseVietnamDateTime = function (value) {
    if (!value) return null;
    if (value instanceof Date) {
      return Number.isNaN(value.getTime()) ? null : value;
    }

    let input = String(value).trim().replace(" ", "T");
    if (!input) return null;
    if (!/(?:[zZ]|[+-]\d{2}:\d{2})$/.test(input)) {
      input = input.includes("T")
        ? `${input}+07:00`
        : `${input}T00:00:00+07:00`;
    }
    const parsed = new Date(input);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  };

  global.formatVietnamDateTime = function (value, options = {}) {
    const date = global.parseVietnamDateTime(value);
    if (!date) return "—";
    return new Intl.DateTimeFormat("vi-VN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      ...options,
      timeZone: vietnamTimeZone,
    }).format(date);
  };
})(window);
